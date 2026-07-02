"""Pins the /ask AI Q&A pipeline — see docs/api.md (GET /api/search/ask) and
docs/code-map.md (services/qa.py).

/ask makes a *paid* LLM call. These tests pin everything around that call
without ever making it: the context block and prompts sent to the provider
(request construction), how the provider's answer/tokens/cost flow back into
AIAnswerResponse (response handling), the depth budget that caps token spend,
and the guard paths (empty query, no provider, LLM error) that must not spend
money or crash. `run_text` is always mocked (**mocked** — no billable request).

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AIProvider, Document
from app.services import qa


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestSessionLocal()
    yield db
    db.close()


@pytest.fixture
def quiet_retrieval(monkeypatch):
    """Keep answer_question hermetic: no ChromaDB, no admin-log writes."""
    import app.services.embeddings as embeddings
    monkeypatch.setattr(embeddings, "collection_count", lambda: 0)
    monkeypatch.setattr(qa, "_semantic_scored", lambda query, n: [])
    monkeypatch.setattr(qa, "_log_ask", lambda *a, **k: None)


def _doc(i: int, **kw) -> Document:
    defaults = dict(
        filename=f"doc{i}.pdf", filepath=f"/lib/doc{i}.pdf",
        ocr_status="done", analysis_status="done",
    )
    defaults.update(kw)
    return Document(**defaults)


def _provider(**kw) -> AIProvider:
    defaults = dict(
        name="test-openai", provider_type="openai", api_key="sk-test",
        model="gpt-test", task_type="analysis", sort_order=0, enabled=True,
    )
    defaults.update(kw)
    return AIProvider(**defaults)


# ── Context assembly (what the paid LLM actually receives) ─────────────────────

def test_build_context_numbers_docs_and_includes_metadata():
    # Why:  the context block IS the request body of a paid LLM call — a field
    #       dropped here silently degrades every answer.
    # Doc:  docs/code-map.md — services/qa.py context assembly.
    # Rule: each doc gets a `[i] filename` header plus its Type/Date/Person/
    #       Organization/Amount/Tags/Summary lines; docs joined by `---`.
    d1 = _doc(1, document_type="invoice", document_date=datetime(2024, 5, 1),
              person_first_name="Ivan", person_last_name="Petrov",
              organization="ACME", amount=99.5, amount_currency="EUR",
              tags=["tax", "2024"], summary="Invoice for services")
    d2 = _doc(2, summary="Second doc")
    ctx = qa.build_context([d1, d2], ocr_chars=0)

    assert "[1] doc1.pdf" in ctx and "[2] doc2.pdf" in ctx
    assert "Type: invoice" in ctx
    assert "Date: 2024-05-01" in ctx
    assert "Person: Ivan Petrov" in ctx
    assert "Organization: ACME" in ctx
    assert "Amount: 99.5 EUR" in ctx
    assert "Tags: tax, 2024" in ctx
    assert "Summary: Invoice for services" in ctx
    assert "\n\n---\n\n" in ctx


def test_build_context_ocr_budget_per_depth():
    # Why:  ocr_chars is the token-spend knob — depth 1 must send no OCR text,
    #       deeper levels only a bounded slice.
    # Doc:  docs/api.md §ask depth param; _DEPTH_CFG in services/qa.py.
    # Rule: ocr_chars=0 omits the Text line entirely; ocr_chars=N truncates to N.
    d = _doc(1, ocr_text="A" * 1000)
    assert "Text:" not in qa.build_context([d], ocr_chars=0)
    ctx = qa.build_context([d], ocr_chars=600)
    assert "Text: " + "A" * 600 in ctx
    assert "A" * 601 not in ctx


def test_build_context_skips_empty_fields():
    # Why:  empty metadata must not waste context tokens or confuse the model
    #       with blank fields.
    # Rule: a doc with no metadata yields only its `[i] filename` line.
    ctx = qa.build_context([_doc(1)], ocr_chars=600)
    assert ctx == "[1] doc1.pdf"


def test_build_prompts_language_and_citation_instructions():
    # Why:  the system prompt drives answer language and the `[n]` citations the
    #       UI links back to source documents.
    # Doc:  docs/api.md §ask — answer references sources by number.
    # Rule: response language follows the UI lang (unknown → English); user
    #       message embeds the context and the question.
    system, user = qa.build_prompts("CTX", "who am I?", "ru")
    assert "Respond in Russian." in system
    assert "[1]" in system  # citation instruction
    assert "CTX" in user and "Question: who am I?" in user

    system_xx, _ = qa.build_prompts("CTX", "q", "xx")
    assert "Respond in English." in system_xx


def test_depth_cfg_budgets():
    # Why:  these three numbers cap retrieval size and token spend per request;
    #       an accidental bump makes every /ask call more expensive.
    # Doc:  docs/api.md §ask depth param (1=fast/2=normal/3=deep).
    # Rule: documented budgets for retrieve/send/ocr_chars per depth level.
    assert qa._DEPTH_CFG[1] == {"n_retrieve": 6,  "n_send": 4,  "ocr_chars": 0}
    assert qa._DEPTH_CFG[2] == {"n_retrieve": 12, "n_send": 6,  "ocr_chars": 600}
    assert qa._DEPTH_CFG[3] == {"n_retrieve": 20, "n_send": 12, "ocr_chars": 1500}


# ── answer_question guard paths (must never spend money) ───────────────────────

def test_empty_query_short_circuits_without_any_calls(db_session, quiet_retrieval, monkeypatch):
    # Why:  a blank query must not trigger retrieval or a paid LLM call.
    # Rule: empty/whitespace query → empty answer, no sources, cost 0.
    async def _boom(*a, **k):
        raise AssertionError("run_text must not be called")
    import app.services.ai_analysis as ai_analysis
    monkeypatch.setattr(ai_analysis, "run_text", _boom)

    resp = asyncio.run(qa.answer_question(db_session, "   "))
    assert resp.answer == "" and resp.sources == [] and resp.cost == 0.0


def test_no_provider_returns_sources_without_llm_call(db_session, quiet_retrieval, monkeypatch):
    # Why:  with no enabled analysis provider the pipeline must still return
    #       the retrieved sources — and must not attempt a billable call.
    # Doc:  docs/api.md §ask — `no_provider` response flag.
    # Rule: no enabled provider → no_provider=True, retrieved docs still listed.
    db = db_session
    db.add(_doc(1, summary="hello world tax paper"))
    db.commit()

    async def _boom(*a, **k):
        raise AssertionError("run_text must not be called")
    import app.services.ai_analysis as ai_analysis
    monkeypatch.setattr(ai_analysis, "run_text", _boom)

    resp = asyncio.run(qa.answer_question(db, "tax"))
    assert resp.no_provider is True
    assert [s.id for s in resp.sources] == [1]
    assert resp.cost == 0.0


# ── answer_question with a (mocked) provider ───────────────────────────────────

def test_llm_receives_context_and_response_flows_back(db_session, quiet_retrieval, monkeypatch):
    # Why:  pins both halves of the paid call: the request (provider row +
    #       system/user prompts with doc context and question) and the response
    #       mapping (answer/tokens/cost → AIAnswerResponse fields).
    # Doc:  docs/api.md §ask response fields; docs/ai-usage.md (qa usage rows).
    # Rule: run_text gets the picked provider and prompts containing the doc
    #       context + question; its 4-tuple lands 1:1 in the response; the call
    #       is recorded in the ai_usage ledger with usage_type="qa".
    db = db_session
    db.add(_doc(1, summary="électricité facture EDF", ocr_text="kWh 123"))
    db.add(_provider())
    db.commit()

    calls = {}

    async def _fake_run_text(provider, system, user):
        calls["provider"] = provider
        calls["system"] = system
        calls["user"] = user
        return "Answer [1]", 111, 22, 0.00042
    import app.services.ai_analysis as ai_analysis
    monkeypatch.setattr(ai_analysis, "run_text", _fake_run_text)

    usage_rows = []
    import app.services.usage as usage
    monkeypatch.setattr(usage, "record_usage", lambda **kw: usage_rows.append(kw))

    resp = asyncio.run(qa.answer_question(db, "facture EDF", language="fr", depth=2))

    # request construction
    assert calls["provider"].name == "test-openai"
    assert "Respond in French." in calls["system"]
    assert "[1] doc1.pdf" in calls["user"]
    assert "Summary: électricité facture EDF" in calls["user"]
    assert "Text: kWh 123" in calls["user"]          # depth 2 → ocr_chars=600
    assert "Question: facture EDF" in calls["user"]

    # response mapping
    assert resp.answer == "Answer [1]"
    assert resp.tokens_in == 111 and resp.tokens_out == 22
    assert resp.cost == 0.00042
    assert resp.model_name == "gpt-test"
    assert resp.docs_sent == 1 and resp.depth == 2

    # usage ledger
    assert len(usage_rows) == 1
    row = usage_rows[0]
    assert row["usage_type"] == "qa"
    assert row["provider_type"] == "openai"
    assert row["model"] == "gpt-test"
    assert row["tokens_in"] == 111 and row["tokens_out"] == 22
    assert row["cost_usd"] == 0.00042


def test_provider_priority_lowest_sort_order_wins(db_session, quiet_retrieval, monkeypatch):
    # Why:  which provider answers /ask decides who gets billed — must follow
    #       the same sort_order priority as the rest of the app.
    # Doc:  docs/code-map.md — AIProvider.sort_order: "lower = higher priority".
    # Rule: enabled analysis/both provider with the lowest sort_order is used;
    #       disabled and vision-only providers are skipped.
    db = db_session
    db.add(_doc(1, summary="tax"))
    db.add(_provider(name="disabled", enabled=False, sort_order=0))
    db.add(_provider(name="vision-only", task_type="vision", sort_order=0))
    db.add(_provider(name="second", sort_order=5))
    db.add(_provider(name="first", sort_order=1))
    db.commit()

    picked = {}

    async def _fake_run_text(provider, system, user):
        picked["name"] = provider.name
        return "ok", 1, 1, 0.0
    import app.services.ai_analysis as ai_analysis
    monkeypatch.setattr(ai_analysis, "run_text", _fake_run_text)
    import app.services.usage as usage
    monkeypatch.setattr(usage, "record_usage", lambda **kw: None)

    asyncio.run(qa.answer_question(db, "tax"))
    assert picked["name"] == "first"


def test_llm_failure_returns_error_text_and_zero_cost(db_session, quiet_retrieval, monkeypatch):
    # Why:  a provider outage must not 500 the endpoint or record phantom spend.
    # Rule: run_text raising → the exception text becomes the answer, tokens
    #       and cost stay 0, and the response still carries the sources.
    db = db_session
    db.add(_doc(1, summary="tax"))
    db.add(_provider())
    db.commit()

    async def _fake_run_text(provider, system, user):
        raise RuntimeError("quota exceeded")
    import app.services.ai_analysis as ai_analysis
    monkeypatch.setattr(ai_analysis, "run_text", _fake_run_text)
    import app.services.usage as usage
    monkeypatch.setattr(usage, "record_usage", lambda **kw: None)

    resp = asyncio.run(qa.answer_question(db, "tax"))
    assert resp.answer == "quota exceeded"
    assert resp.tokens_in == 0 and resp.tokens_out == 0 and resp.cost == 0.0
    assert [s.id for s in resp.sources] == [1]
