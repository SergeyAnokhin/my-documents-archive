"""Pins AI-analysis output parsing and request construction — see
docs/code-map.md (services/ai_analysis.py).

`_parse_result` turns raw LLM text into an `AnalysisResult`. The non-trivial rules
worth pinning: tolerate markdown code fences, coerce field types, and normalise
empty/absent fields to None / documented defaults.

`_call_openai_compatible` / `_call_gemini` build the actual outbound request to a
paid provider API. These are mocked at the SDK boundary (openai.AsyncOpenAI /
google.genai.Client) so the tests pin the request shape (model/base_url defaults,
json-mode flags) without making a real, billable call.

Each test carries:
  Doc:  which documented area it protects (or "none" for code-only behavior)
  Rule: the specific behavior it asserts
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai_analysis import _call_gemini, _call_openai_compatible, _parse_result
from app.services.ai_common import SyntheticProvider


def test_parse_result_strips_json_code_fence():
    # Doc:  none in prose docs — pins the `_parse_result` docstring ("tolerating
    #       markdown code fences"). ai_analysis.py is documented at docs/code-map.md,
    #       but fence-stripping is a robustness detail in the function itself.
    # Rule: a ```json … ``` fence is stripped before JSON parsing.
    raw = '```json\n{"summary": "hello", "document_type": "invoice"}\n```'
    r = _parse_result(raw)
    assert r.summary == "hello"
    assert r.document_type == "invoice"


def test_parse_result_coerces_types():
    # Doc:  docs/code-map.md → services/ai_analysis.py lists the output fields
    #       (summary, document_type +confidence, tags, amount). No prose rule on
    #       coercion itself — this guards against an LLM returning loose JSON types.
    # Rule: summary→str, confidence→float, every tag→str, amount→float.
    raw = (
        '{"summary": 42, "document_type_confidence": "0.8", '
        '"tags": ["a", 7], "amount": "150.5"}'
    )
    r = _parse_result(raw)
    assert r.summary == "42"                 # str() coercion
    assert r.document_type_confidence == 0.8  # float() coercion
    assert r.tags == ["a", "7"]              # every tag stringified
    assert r.amount == 150.5                 # float() coercion


def test_parse_result_normalises_empty_and_absent_fields_to_none():
    # Doc:  docs/code-map.md / ANALYSIS_SYSTEM prompt — optional fields are
    #       "<value> or null if absent" (organization, amount, currency, person…).
    # Rule: empty string and JSON null both normalise to Python None.
    r = _parse_result('{"organization": "", "amount": null}')
    assert r.organization is None   # "" → None
    assert r.amount is None          # null stays None
    assert r.amount_currency is None
    assert r.person_first_name is None


def test_parse_result_applies_documented_defaults():
    # Doc:  docs/code-map.md §Gotchas ("unclassified vs other") and the
    #       ANALYSIS_SYSTEM prompt ("Use 'unclassified' if it does not fit").
    # Rule: missing document_type → "unclassified", missing confidence → 0.0.
    r = _parse_result("{}")
    assert r.document_type == "unclassified"
    assert r.document_type_confidence == 0.0
    assert r.summary == ""
    assert r.tags == []


def test_parse_result_raises_on_non_json():
    # Doc:  none — general test. `analyze_document()` relies on a parse failure
    #       raising so it can fail over to the next provider (see its try/except).
    # Rule: non-JSON input raises (json.JSONDecodeError ⊂ ValueError).
    with pytest.raises(ValueError):
        _parse_result("not json at all")


# ── _call_openai_compatible: request construction ───────────────────────────────

def _mock_openai_client(content: str = "{}", tin: int = 10, tout: int = 5):
    """Build a fake openai.AsyncOpenAI() instance whose create() call is inspectable."""
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=tin, completion_tokens=tout),
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    ctor = MagicMock(return_value=client)
    return ctor, client


def test_call_openai_compatible_uses_per_provider_model_and_base_url_defaults():
    # Doc:  docs/code-map.md → services/ai_analysis.py (provider_type dispatch)
    # Rule: when provider.model/base_url are unset, deepseek gets its documented
    #       default model + base_url baked into the outbound request.
    provider = SyntheticProvider(name="ds", provider_type="deepseek", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compatible(provider, "hello"))

    assert ctor.call_args.kwargs == {"api_key": "k", "base_url": "https://api.deepseek.com/v1"}
    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == "deepseek-chat"


def test_call_openai_compatible_respects_explicit_model_and_base_url():
    # Doc:  docs/code-map.md — AIProvider rows carry an explicit model/base_url
    # Rule: an explicit provider.model/base_url override the per-type defaults.
    provider = SyntheticProvider(
        name="custom", provider_type="mistral", api_key="k",
        base_url="https://custom.example/v1", model="mistral-medium-latest",
    )
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compatible(provider, "hello"))

    assert ctor.call_args.kwargs["base_url"] == "https://custom.example/v1"
    assert client.chat.completions.create.call_args.kwargs["model"] == "mistral-medium-latest"


def test_call_openai_compatible_forces_json_response_format_for_openai():
    # Doc:  ANALYSIS_SYSTEM prompt requires a raw JSON object back
    # Rule: for provider_type "openai", response_format is forced to json_object
    #       even when json_mode=False (other providers only get it when json_mode=True).
    provider = SyntheticProvider(name="oa", provider_type="openai", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compatible(provider, "hello", json_mode=False))

    assert client.chat.completions.create.call_args.kwargs["response_format"] == {"type": "json_object"}


def test_call_openai_compatible_json_mode_forces_response_format_for_any_provider():
    # Doc:  none — pins the `provider.provider_type == "openai" or json_mode` branch
    # Rule: json_mode=True forces response_format on a non-openai provider too.
    provider = SyntheticProvider(name="ds", provider_type="deepseek", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compatible(provider, "hello", json_mode=True))

    assert client.chat.completions.create.call_args.kwargs["response_format"] == {"type": "json_object"}


def test_call_openai_compatible_omits_response_format_when_not_json_and_not_openai():
    # Doc:  none — the counterpart of the two tests above
    # Rule: no response_format key is sent for a non-openai provider without json_mode.
    provider = SyntheticProvider(name="or", provider_type="openrouter", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compatible(provider, "hello", json_mode=False))

    assert "response_format" not in client.chat.completions.create.call_args.kwargs


def test_call_openai_compatible_sends_system_and_user_messages():
    # Doc:  ANALYSIS_SYSTEM / SUGGEST_TYPES_SYSTEM prompts
    # Rule: the messages array carries exactly the given system + user content, in order.
    provider = SyntheticProvider(name="oa", provider_type="openai", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compatible(provider, "the user text", "the system text"))

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert messages == [
        {"role": "system", "content": "the system text"},
        {"role": "user", "content": "the user text"},
    ]


def test_call_openai_compatible_returns_text_and_usage_derived_cost():
    # Doc:  services/pricing.py — cost is derived from (model, tokens_in, tokens_out)
    # Rule: the parsed response text and token counts flow back to the caller,
    #       and cost is 0.0 for a model with no pricing entry rather than raising.
    provider = SyntheticProvider(name="oa", provider_type="openai", api_key="k", model="not-a-real-model")
    ctor, client = _mock_openai_client(content='{"summary":"x"}', tin=100, tout=50)
    with patch("openai.AsyncOpenAI", ctor):
        text, tin, tout, cost = asyncio.run(_call_openai_compatible(provider, "hello"))

    assert text == '{"summary":"x"}'
    assert (tin, tout) == (100, 50)
    assert cost == 0.0


# ── _call_gemini: request construction ──────────────────────────────────────────

def _mock_gemini_client(text: str = "{}", tin: int = 10, tout: int = 5):
    """Build a fake google.genai.Client() instance whose generate_content() is inspectable."""
    resp = SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=tin, candidates_token_count=tout),
    )
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=resp)
    ctor = MagicMock(return_value=client)
    return ctor, client


def test_call_gemini_uses_default_model_and_system_instruction():
    # Doc:  docs/code-map.md → services/ai_analysis.py
    # Rule: with no provider.model set, "gemini-2.5-flash" is used and the system
    #       prompt is passed as system_instruction (not concatenated into contents).
    provider = SyntheticProvider(name="g", provider_type="gemini", api_key="k")
    ctor, client = _mock_gemini_client()
    with patch("google.genai.Client", ctor):
        asyncio.run(_call_gemini(provider, "hello", "sys prompt"))

    call = client.aio.models.generate_content.call_args.kwargs
    assert call["model"] == "gemini-2.5-flash"
    assert call["contents"] == "hello"
    assert call["config"].system_instruction == "sys prompt"


def test_call_gemini_json_mode_sets_response_mime_type():
    # Doc:  none — pins the json_mode branch of _call_gemini's config
    # Rule: json_mode=True sets response_mime_type to application/json; False omits it.
    provider = SyntheticProvider(name="g", provider_type="gemini", api_key="k")
    ctor, client = _mock_gemini_client()
    with patch("google.genai.Client", ctor):
        asyncio.run(_call_gemini(provider, "hello", "sys", json_mode=True))
    assert client.aio.models.generate_content.call_args.kwargs["config"].response_mime_type == "application/json"

    ctor2, client2 = _mock_gemini_client()
    with patch("google.genai.Client", ctor2):
        asyncio.run(_call_gemini(provider, "hello", "sys", json_mode=False))
    assert client2.aio.models.generate_content.call_args.kwargs["config"].response_mime_type is None


def test_call_gemini_missing_usage_metadata_defaults_tokens_to_zero():
    # Doc:  none — guards the `getattr(um, ..., 0) or 0` defensive coercions
    # Rule: a response with no usage_metadata still returns (text, 0, 0, 0.0) instead of raising.
    provider = SyntheticProvider(name="g", provider_type="gemini", api_key="k")
    resp = SimpleNamespace(text="hi", usage_metadata=None)
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=resp)
    with patch("google.genai.Client", MagicMock(return_value=client)):
        text, tin, tout, cost = asyncio.run(_call_gemini(provider, "hello", "sys"))

    assert (text, tin, tout, cost) == ("hi", 0, 0, 0.0)
