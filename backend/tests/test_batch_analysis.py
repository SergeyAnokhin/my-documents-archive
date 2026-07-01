"""Pins the Gemini text-only batch-analysis request/response handling — see
docs/code-map.md (services/batch_analysis.py) and docs/batch-ocr.md (analogous
Gemini Batch flow).

`run_batch_analysis_gemini()` selects documents, builds a Gemini Batch API JSONL
request, uploads/submits/polls/downloads via httpx, then writes parsed results
back onto Document rows. All httpx calls are mocked (no network, no cost) and
the function is driven end-to-end against an in-memory SQLite DB, pinning:
the `doc_scope` selection filters, the JSONL request shape, and the result-line
parsing (success/error/bad-date branches).

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import AIProvider, Document, Task
from app.services import batch_analysis, task_runtime
from app.services import usage as usage_module
from app.services.batch_analysis import run_batch_analysis_gemini

UPLOAD_URL = "https://upload.example/put"
FILE_NAME = "files/abc123"
BATCH_JOB_NAME = "batchOperations/999"
OUTPUT_FILE = "files/output-xyz"


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr(batch_analysis, "SessionLocal", SessionLocal)
    monkeypatch.setattr(task_runtime, "SessionLocal", SessionLocal)
    monkeypatch.setattr(usage_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    monkeypatch.setattr("app.services.indexer._run_embedding", AsyncMock())
    monkeypatch.setattr(batch_analysis, "_log", lambda *a, **k: None)

    db = SessionLocal()
    provider = AIProvider(name="g", provider_type="gemini", api_key="k", enabled=True, sort_order=0, task_type="both")
    db.add(provider)
    task = Task(task_type="batch_analysis_gemini", title="t", status="running")
    db.add(task)
    db.commit()
    db.refresh(provider)
    db.refresh(task)
    ids = SimpleNamespace(provider_id=provider.id, task_id=task.id)
    db.close()

    return SimpleNamespace(SessionLocal=SessionLocal, **vars(ids))


def _add_doc(SessionLocal, **kwargs) -> int:
    db = SessionLocal()
    defaults = dict(filename="d.pdf", filepath=f"/lib/{kwargs.get('filename', 'd.pdf')}-{id(kwargs)}")
    defaults.update(kwargs)
    doc = Document(**defaults)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    doc_id = doc.id
    db.close()
    return doc_id


def _get_doc(SessionLocal, doc_id: int) -> Document:
    db = SessionLocal()
    doc = db.query(Document).filter(Document.id == doc_id).first()
    db.expunge(doc)
    db.close()
    return doc


def _mock_httpx(captured: dict, poll_sequence: list, download_text: str):
    """Fake httpx.AsyncClient() whose .post()/.get() dispatch by URL to canned
    responses, capturing the uploaded JSONL body and batch-create payload."""
    poll_iter = iter(poll_sequence)

    async def _post(url, **kwargs):
        if url == f"{batch_analysis.GEMINI_BATCH_BASE}/upload/v1beta/files":
            resp = MagicMock(headers={"x-goog-upload-url": UPLOAD_URL})
            resp.raise_for_status = MagicMock()
            return resp
        if url == UPLOAD_URL:
            captured["jsonl_bytes"] = kwargs.get("content")
            resp = MagicMock()
            resp.json.return_value = {"file": {"name": FILE_NAME}}
            resp.raise_for_status = MagicMock()
            return resp
        if url.endswith(":batchGenerateContent"):
            captured["batch_create_body"] = kwargs.get("json")
            resp = MagicMock()
            resp.json.return_value = {"name": BATCH_JOB_NAME}
            resp.raise_for_status = MagicMock()
            return resp
        raise AssertionError(f"unexpected POST {url}")

    async def _get(url, **kwargs):
        if url == f"{batch_analysis.GEMINI_BATCH_BASE}/v1beta/{BATCH_JOB_NAME}":
            resp = MagicMock()
            resp.json.return_value = next(poll_iter)
            resp.raise_for_status = MagicMock()
            return resp
        if url == f"{batch_analysis.GEMINI_BATCH_BASE}/download/v1beta/{OUTPUT_FILE}:download":
            resp = MagicMock(text=download_text)
            resp.raise_for_status = MagicMock()
            return resp
        raise AssertionError(f"unexpected GET {url}")

    client = MagicMock()
    client.post = AsyncMock(side_effect=_post)
    client.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _jsonl_lines(raw_bytes: bytes) -> list[dict]:
    return [json.loads(line) for line in raw_bytes.decode().splitlines() if line.strip()]


DONE_POLL = [{"done": True, "response": {"responsesFile": OUTPUT_FILE}}]


def _run(env, config):
    import asyncio
    captured = config.pop("_captured", {})
    poll_sequence = config.pop("_poll", DONE_POLL)
    download_text = config.pop("_download", "")
    with patch("httpx.AsyncClient", _mock_httpx(captured, poll_sequence, download_text)):
        asyncio.run(run_batch_analysis_gemini(env.task_id, config))
    return captured


# ── No provider / no documents: early-exit branches ─────────────────────────────

def test_no_gemini_provider_finishes_with_error(env, monkeypatch):
    # Doc:  services/batch_analysis.py — run_batch_analysis_gemini step 1
    # Rule: with zero configured Gemini providers, the task is marked "error"
    #       and no network call is ever attempted.
    db = env.SessionLocal()
    db.query(AIProvider).delete()
    db.commit()
    db.close()

    _run(env, {})

    db = env.SessionLocal()
    task = db.query(Task).filter(Task.id == env.task_id).first()
    assert task.status == "error"
    db.close()


def test_no_matching_documents_finishes_done_with_zero_processed(env):
    # Doc:  services/batch_analysis.py — run_batch_analysis_gemini step 2
    # Rule: when no document matches doc_scope, the task finishes "done" with
    #       processed=0 rather than submitting an empty batch job.
    _run(env, {})

    db = env.SessionLocal()
    task = db.query(Task).filter(Task.id == env.task_id).first()
    assert task.status == "done"
    assert task.result_summary["processed"] == 0
    db.close()


# ── doc_scope selection filters ──────────────────────────────────────────────────

@pytest.mark.parametrize("doc_scope,expected_included,make_docs", [
    (
        "needs_analysis",
        {"a", "e"},
        lambda SL: {
            "a": _add_doc(SL, filename="a", ocr_text="A" * 10, manually_classified=False, analysis_status="pending"),
            "b": _add_doc(SL, filename="b", ocr_text="B" * 10, manually_classified=True, analysis_status="pending"),
            "c": _add_doc(SL, filename="c", ocr_text=None, manually_classified=False, analysis_status="pending"),
            "d": _add_doc(SL, filename="d", ocr_text="D" * 10, manually_classified=False, analysis_status="done", document_type="invoice"),
            "e": _add_doc(SL, filename="e", ocr_text="E" * 10, manually_classified=False, analysis_status="done", document_type="unclassified"),
        },
    ),
    (
        "unclassified",
        {"f"},
        lambda SL: {
            "f": _add_doc(SL, filename="f", ocr_status="done", ocr_text="F" * 5, manually_classified=False, document_type="unclassified"),
            "g": _add_doc(SL, filename="g", ocr_status="pending", ocr_text="G" * 5, manually_classified=False, document_type="unclassified"),
            "h": _add_doc(SL, filename="h", ocr_status="done", ocr_text="H" * 5, manually_classified=True, document_type="unclassified"),
            "i": _add_doc(SL, filename="i", ocr_status="done", ocr_text="I" * 5, manually_classified=False, document_type="invoice"),
        },
    ),
    (
        "pending",
        {"j"},
        lambda SL: {
            "j": _add_doc(SL, filename="j", ocr_status="done", ocr_text="J" * 5, analysis_status="pending"),
            "k": _add_doc(SL, filename="k", ocr_status="done", ocr_text="K" * 5, analysis_status="done"),
            "l": _add_doc(SL, filename="l", ocr_status="pending", ocr_text="L" * 5, analysis_status="pending"),
        },
    ),
], ids=["needs_analysis", "unclassified", "pending"])
def test_doc_scope_filters_select_expected_documents(env, doc_scope, expected_included, make_docs):
    # Doc:  docs/code-map.md — services/batch_analysis.py doc_scope values
    # Rule: each doc_scope applies its documented filter combination; only the
    #       matching documents end up as JSONL request lines.
    doc_ids = make_docs(env.SessionLocal)
    captured = _run(env, {"doc_scope": doc_scope, "_captured": {}})

    lines = _jsonl_lines(captured["jsonl_bytes"])
    sent_ids = {line["key"] for line in lines}
    expected = {str(doc_ids[label]) for label in expected_included}
    assert sent_ids == expected


def test_doc_scope_explicit_doc_ids_overrides_scope_and_skips_empty_text(env):
    # Doc:  docs/code-map.md — services/batch_analysis.py doc_ids param
    # Rule: an explicit doc_ids list bypasses the doc_scope filters entirely,
    #       but a document with no usable text is still skipped from the request.
    with_text = _add_doc(env.SessionLocal, filename="m", ocr_text="M" * 10, document_type="invoice", analysis_status="done")
    no_text = _add_doc(env.SessionLocal, filename="n", ocr_text=None, document_type="invoice", analysis_status="done")

    captured = _run(env, {"doc_ids": [with_text, no_text], "_captured": {}})

    lines = _jsonl_lines(captured["jsonl_bytes"])
    assert {line["key"] for line in lines} == {str(with_text)}


# ── JSONL request shape ───────────────────────────────────────────────────────────

def test_jsonl_request_line_shape_matches_gemini_batch_schema(env):
    # Doc:  docs/code-map.md — services/batch_analysis.py (Gemini Batch API JSONL)
    # Rule: each line is {"key": doc_id, "request": {system_instruction, contents,
    #       generation_config}} with the OCR text prefixed "OCR Text:\n" and the
    #       shared ANALYSIS_SYSTEM prompt as the system instruction.
    doc_id = _add_doc(env.SessionLocal, filename="o", ocr_text="Some OCR content", analysis_status="pending")

    captured = _run(env, {"_captured": {}})
    lines = _jsonl_lines(captured["jsonl_bytes"])
    assert len(lines) == 1
    line = lines[0]
    assert line["key"] == str(doc_id)
    req = line["request"]
    assert req["system_instruction"] == {"parts": [{"text": batch_analysis.ANALYSIS_SYSTEM}]}
    assert req["contents"] == [{"parts": [{"text": "OCR Text:\nSome OCR content"}]}]
    assert req["generation_config"] == {"max_output_tokens": 1024}


# ── result-line parsing ────────────────────────────────────────────────────────────

def _gemini_result_line(key: str, text: str, tin: int = 20, tout: int = 10) -> str:
    return json.dumps({
        "key": key,
        "response": {
            "candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": tin, "candidatesTokenCount": tout},
        },
    })


def test_response_success_line_writes_all_fields_and_marks_done(env):
    # Doc:  docs/code-map.md — services/batch_analysis.py step 8 (save results)
    # Rule: a successful result line's JSON fields are written onto the matching
    #       Document, analysis_status becomes "done", and classification_source="auto".
    doc_id = _add_doc(env.SessionLocal, filename="p", ocr_text="text", analysis_status="pending")
    payload = json.dumps({
        "summary": "A summary", "document_type": "invoice", "document_type_confidence": 0.9,
        "tags": ["x", "y"], "language": "en", "organization": "Acme", "amount": 12.5,
        "amount_currency": "USD", "document_date": "2024-01-15",
    })
    result_line = _gemini_result_line(str(doc_id), payload)

    _run(env, {"_download": result_line})

    doc = _get_doc(env.SessionLocal, doc_id)
    assert doc.summary == "A summary"
    assert doc.document_type == "invoice"
    assert doc.classification_confidence == 0.9
    assert doc.classification_source == "auto"
    assert doc.tags == ["x", "y"]
    assert doc.organization == "Acme"
    assert doc.amount == 12.5
    assert doc.analysis_status == "done"


def test_response_error_line_counts_as_failed_and_leaves_document_untouched(env):
    # Doc:  docs/code-map.md — services/batch_analysis.py step 8
    # Rule: a per-line {"error": {...}} response is counted as failed and the
    #       document is left unmodified (analysis_status stays "pending").
    doc_id = _add_doc(env.SessionLocal, filename="q", ocr_text="text", analysis_status="pending")
    result_line = json.dumps({"key": str(doc_id), "error": {"message": "quota exceeded"}})

    _run(env, {"_download": result_line})

    doc = _get_doc(env.SessionLocal, doc_id)
    assert doc.analysis_status == "pending"

    db = env.SessionLocal()
    task = db.query(Task).filter(Task.id == env.task_id).first()
    assert task.result_summary["failed"] == 1
    db.close()


def test_response_invalid_document_date_is_stored_as_none_not_raised(env):
    # Doc:  docs/code-map.md — services/batch_analysis.py step 8
    # Rule: an unparsable document_date string is stored as None instead of
    #       raising and aborting the whole batch-result save.
    doc_id = _add_doc(env.SessionLocal, filename="r", ocr_text="text", analysis_status="pending")
    payload = json.dumps({"summary": "s", "document_type": "invoice", "document_date": "not-a-date"})
    result_line = _gemini_result_line(str(doc_id), payload)

    _run(env, {"_download": result_line})

    doc = _get_doc(env.SessionLocal, doc_id)
    assert doc.document_date is None
    assert doc.analysis_status == "done"   # the rest of the line still saved


# ── resume path ────────────────────────────────────────────────────────────────────

def test_resume_batch_job_id_skips_submission_and_only_polls(env):
    # Doc:  docs/batch-ocr.md §Resume support (same pattern reused here)
    # Rule: resume_batch_job_id skips document collection/upload/create — only
    #       the existing job is polled and its results downloaded.
    doc_id = _add_doc(env.SessionLocal, filename="s", ocr_text="text", analysis_status="pending")
    payload = json.dumps({"summary": "resumed", "document_type": "invoice"})
    result_line = _gemini_result_line(str(doc_id), payload)

    captured: dict = {}
    with patch("httpx.AsyncClient", _mock_httpx(captured, DONE_POLL, result_line)):
        import asyncio
        asyncio.run(run_batch_analysis_gemini(env.task_id, {"resume_batch_job_id": BATCH_JOB_NAME}))

    assert "jsonl_bytes" not in captured        # no upload happened
    assert "batch_create_body" not in captured  # no batch-create call happened
    doc = _get_doc(env.SessionLocal, doc_id)
    assert doc.summary == "resumed"
