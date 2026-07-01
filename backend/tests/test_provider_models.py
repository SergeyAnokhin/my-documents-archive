"""Pins model-list fetching/pricing-inference for AI provider APIs — see
docs/code-map.md (services/provider_models.py).

`fetch_models()` calls each provider's public "/models" listing endpoint (free —
listing models doesn't cost tokens) and reshapes the response into a uniform
dict. The reshaping logic (dedup, deprecated-model filtering, pricing inference
for unlisted Gemini models, negative-price clamping for OpenRouter, sort order)
is non-trivial and directly feeds the model picker shown when configuring a
paid provider, so it's pinned here. All HTTP calls are mocked (httpx.AsyncClient)
so these tests run offline.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.provider_models import (
    KNOWN_MODELS,
    _enrich,
    _fetch_gemini,
    _fetch_mistral,
    _fetch_openai_compat,
    _fetch_openrouter,
    _gemini_infer_pricing,
    _is_gemini_deprecated,
    _mistral_ocr_models,
    fetch_models,
)


def _mock_httpx_get(json_data: dict):
    """Fake httpx.AsyncClient() context manager whose .get() returns json_data."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctor = MagicMock(return_value=ctx)
    return ctor, client


# ── _is_gemini_deprecated / _gemini_infer_pricing ───────────────────────────────

def test_is_gemini_deprecated_matches_exact_and_versioned():
    # Doc:  services/provider_models.py — _GEMINI_DEPRECATED_PREFIXES
    # Rule: an exact deprecated id and a "<prefix>-<suffix>" snapshot both match;
    #       an unrelated model does not.
    assert _is_gemini_deprecated("gemini-1.5-flash") is True
    assert _is_gemini_deprecated("gemini-1.5-flash-002") is True
    assert _is_gemini_deprecated("gemini-2.5-flash") is False


def test_gemini_infer_pricing_gemma_is_free():
    # Doc:  services/provider_models.py — _gemini_infer_pricing
    # Rule: open-source Gemma models are priced free through AI Studio.
    info = _gemini_infer_pricing("gemma-2-9b-it")
    assert info == {"in": 0.0, "out": 0.0, "vision": False}


def test_gemini_infer_pricing_pro_tier_keywords():
    # Doc:  services/provider_models.py — _gemini_infer_pricing
    # Rule: "pro"/"research"/"robotics"/"ultra" in the id → pro-tier pricing.
    assert _gemini_infer_pricing("gemini-4.0-pro-preview") == {"in": 1.25, "out": 10.0, "vision": True}


def test_gemini_infer_pricing_flash_lite_tier_keywords():
    # Doc:  services/provider_models.py — _gemini_infer_pricing
    # Rule: "flash-lite"/"flash-8b"/"nano"/"clip" → flash-lite-tier pricing.
    assert _gemini_infer_pricing("gemini-4.0-flash-lite") == {"in": 0.075, "out": 0.30, "vision": True}


def test_gemini_infer_pricing_unknown_model_defaults_to_flash_tier():
    # Doc:  services/provider_models.py — _gemini_infer_pricing
    # Rule: a model matching none of the known keyword groups still gets the
    #       conservative flash-tier estimate rather than raising/erroring.
    assert _gemini_infer_pricing("totally-unrecognised-model") == {"in": 0.10, "out": 0.40, "vision": True}


# ── _enrich ──────────────────────────────────────────────────────────────────────

def test_enrich_known_model_uses_known_models_table():
    # Doc:  services/provider_models.py — KNOWN_MODELS
    # Rule: a model present in KNOWN_MODELS uses its pricing/name/vision/ctx verbatim.
    item = _enrich("gpt-4o-mini")
    known = KNOWN_MODELS["gpt-4o-mini"]
    assert item["name"] == known["name"]
    assert item["price_in"] == known["in"]
    assert item["supports_vision"] == known["vision"]
    assert item["is_free"] is False


def test_enrich_unknown_gemini_model_falls_back_to_inference():
    # Doc:  services/provider_models.py — _enrich → _gemini_infer_pricing
    # Rule: an unknown model is only pricing-inferred when provider_type="gemini".
    item = _enrich("gemini-9.9-flash-preview", provider_type="gemini")
    assert item["price_in"] == 0.10
    assert item["supports_vision"] is True


def test_enrich_unknown_non_gemini_model_has_no_pricing():
    # Doc:  services/provider_models.py — _enrich
    # Rule: an unknown model for a non-gemini provider gets no price/vision info,
    #       just its id/display_name passed through.
    item = _enrich("some-custom-model", display_name="Custom", provider_type="deepseek")
    assert item == {
        "id": "some-custom-model", "name": "Custom", "supports_vision": False,
        "context_length": None, "price_in": None, "price_out": None, "is_free": False,
    }


# ── fetch_models: dispatch ───────────────────────────────────────────────────────

def test_fetch_models_dispatches_to_provider_specific_fetcher():
    # Doc:  services/provider_models.py — fetch_models()
    # Rule: each provider_type routes to its dedicated fetcher.
    with patch("app.services.provider_models._fetch_openrouter", new=AsyncMock(return_value=["x"])) as m:
        result = asyncio.run(fetch_models("openrouter", "key"))
    assert result == ["x"]
    m.assert_awaited_once_with("key")


def test_fetch_models_never_raises_returns_empty_list_on_error():
    # Doc:  services/provider_models.py — fetch_models() docstring ("Never raises")
    # Rule: if the underlying fetcher raises, fetch_models swallows it and returns [].
    with patch("app.services.provider_models._fetch_gemini", new=AsyncMock(side_effect=RuntimeError("boom"))):
        result = asyncio.run(fetch_models("gemini", "key"))
    assert result == []


def test_fetch_models_deepseek_uses_configured_or_default_base_url():
    # Doc:  services/provider_models.py — fetch_models() deepseek branch
    # Rule: an explicit base_url is passed through; otherwise the documented default is used.
    with patch("app.services.provider_models._fetch_openai_compat", new=AsyncMock(return_value=[])) as m:
        asyncio.run(fetch_models("deepseek", "key"))
    m.assert_awaited_once_with("key", "https://api.deepseek.com/v1", "deepseek")


# ── _fetch_mistral ────────────────────────────────────────────────────────────────

def test_fetch_mistral_merges_known_and_unknown_models_excludes_embed():
    # Doc:  services/provider_models.py — _fetch_mistral
    # Rule: known text models present in the API response are enriched; unknown
    #       models are appended; mistral-embed/moderation are always excluded.
    ctor, client = _mock_httpx_get({"data": [
        {"id": "mistral-small-latest"}, {"id": "brand-new-model"},
        {"id": "mistral-embed"}, {"id": "mistral-moderation-latest"},
    ]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_mistral("key"))

    ids = [m["id"] for m in result]
    assert ids[0] == "mistral-ocr-latest"          # OCR model always first
    assert "mistral-small-latest" in ids
    assert "brand-new-model" in ids
    assert "mistral-embed" not in ids
    assert "mistral-moderation-latest" not in ids


def test_fetch_mistral_falls_back_to_static_list_on_http_error():
    # Doc:  services/provider_models.py — _fetch_mistral
    # Rule: any exception during the API call falls back to the static OCR+known list.
    ctor, client = _mock_httpx_get({})
    client.get.side_effect = RuntimeError("network down")
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_mistral("key"))
    assert result == _mistral_ocr_models()


# ── _fetch_openai_compat ─────────────────────────────────────────────────────────

def test_fetch_openai_compat_openai_filters_to_known_text_models_only():
    # Doc:  services/provider_models.py — _OPENAI_TEXT_MODELS filter
    # Rule: for provider_type "openai", only ids in _OPENAI_TEXT_MODELS survive,
    #       even if the API lists other (embedding/TTS/etc) models too.
    ctor, client = _mock_httpx_get({"data": [
        {"id": "gpt-4o-mini"}, {"id": "gpt-4o"}, {"id": "text-embedding-3-small"},
    ]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_openai_compat("key", "https://api.openai.com/v1", "openai"))

    ids = {m["id"] for m in result}
    assert ids == {"gpt-4o-mini", "gpt-4o"}
    call = client.get.call_args
    assert call.args[0] == "https://api.openai.com/v1/models"
    assert call.kwargs["headers"] == {"Authorization": "Bearer key"}


def test_fetch_openai_compat_deepseek_prefers_known_models():
    # Doc:  services/provider_models.py — _fetch_openai_compat (non-openai branch)
    # Rule: known models present in the API list are preferred over the raw dump.
    ctor, client = _mock_httpx_get({"data": [{"id": "deepseek-chat"}, {"id": "unlisted-model"}]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_openai_compat("key", "https://api.deepseek.com/v1", "deepseek"))
    assert [m["id"] for m in result] == ["deepseek-chat"]


def test_fetch_openai_compat_falls_back_to_all_ids_when_none_known():
    # Doc:  services/provider_models.py — _fetch_openai_compat (non-openai branch)
    # Rule: when no known models are present, every returned id is surfaced (sorted).
    ctor, client = _mock_httpx_get({"data": [{"id": "zeta-model"}, {"id": "alpha-model"}]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_openai_compat("key", "https://example.test/v1", "deepseek"))
    assert [m["id"] for m in result] == ["alpha-model", "zeta-model"]


# ── _fetch_gemini ─────────────────────────────────────────────────────────────────

def _gemini_model(name: str, methods=("generateContent",), display_name="", input_limit=None):
    return {"name": name, "supportedGenerationMethods": list(methods), "displayName": display_name, "inputTokenLimit": input_limit}


def test_fetch_gemini_filters_to_generate_content_and_strips_prefix():
    # Doc:  services/provider_models.py — _fetch_gemini
    # Rule: only models supporting generateContent are kept; "models/" prefix is stripped.
    ctor, client = _mock_httpx_get({"models": [
        _gemini_model("models/gemini-2.5-flash"),
        _gemini_model("models/gemini-embedding-001", methods=["embedContent"]),
    ]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_gemini("key"))
    ids = [m["id"] for m in result]
    assert ids == ["gemini-2.5-flash"]
    call = client.get.call_args
    assert call.kwargs["params"] == {"key": "key"}


def test_fetch_gemini_excludes_deprecated_and_dedupes_versioned_snapshots():
    # Doc:  services/provider_models.py — _fetch_gemini
    # Rule: deprecated-prefixed models are dropped, and a versioned snapshot
    #       (id-NNN) is dropped when its stable alias is also present.
    ctor, client = _mock_httpx_get({"models": [
        _gemini_model("models/gemini-1.5-flash"),          # deprecated → dropped
        _gemini_model("models/gemini-2.5-pro"),             # stable, kept
        _gemini_model("models/gemini-2.5-pro-001"),         # versioned dup → dropped
    ]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_gemini("key"))
    ids = {m["id"] for m in result}
    assert ids == {"gemini-2.5-pro"}


def test_fetch_gemini_all_results_marked_vision_capable():
    # Doc:  docs/code-map.md — "All Gemini models that support generateContent
    #       also support vision (multimodal)"
    # Rule: supports_vision is forced True for every surviving Gemini model.
    ctor, client = _mock_httpx_get({"models": [_gemini_model("models/gemini-2.5-flash-lite")]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_gemini("key"))
    assert result[0]["supports_vision"] is True


def test_fetch_gemini_unknown_model_uses_input_token_limit_as_context_length():
    # Doc:  services/provider_models.py — _fetch_gemini
    # Rule: for a model with no KNOWN_MODELS entry, context_length falls back to
    #       the API's inputTokenLimit field.
    ctor, client = _mock_httpx_get({"models": [
        _gemini_model("models/gemini-9.9-unknown", display_name="Unknown", input_limit=555_000),
    ]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_gemini("key"))
    assert result[0]["context_length"] == 555_000


# ── _fetch_openrouter ─────────────────────────────────────────────────────────────

def test_fetch_openrouter_clamps_negative_sentinel_pricing():
    # Doc:  services/provider_models.py — _fetch_openrouter
    # Rule: OpenRouter's -1 pricing sentinel is clamped to 0.0 (never negative),
    #       which in turn is treated the same as a genuinely free model.
    ctor, client = _mock_httpx_get({"data": [{
        "id": "some/model", "name": "Some Model",
        "pricing": {"prompt": "-1", "completion": "-1"},
        "architecture": {"modality": "text->text"},
    }]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_openrouter("key"))
    assert result[0]["price_in"] is None   # 0.0 is falsy → display coerces to None
    assert result[0]["is_free"] is True    # but the clamped 0.0 still counts as free


def test_fetch_openrouter_detects_vision_from_modality_and_free_models():
    # Doc:  services/provider_models.py — _fetch_openrouter
    # Rule: "image" in the architecture.modality string → supports_vision; a
    #       literal 0 prompt price → is_free.
    ctor, client = _mock_httpx_get({"data": [{
        "id": "vision/model", "name": "Vision Model",
        "pricing": {"prompt": "0", "completion": "0"},
        "architecture": {"modality": "text+image->text"},
    }]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_openrouter("key"))
    assert result[0]["supports_vision"] is True
    assert result[0]["is_free"] is True


def test_fetch_openrouter_sorts_free_first_then_cheapest():
    # Doc:  services/provider_models.py — _fetch_openrouter
    # Rule: free models sort before paid ones; among paid, cheapest prompt price first.
    ctor, client = _mock_httpx_get({"data": [
        {"id": "expensive", "name": "Expensive", "pricing": {"prompt": "0.00005", "completion": "0.0001"}, "architecture": {}},
        {"id": "free", "name": "Free", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {}},
        {"id": "cheap", "name": "Cheap", "pricing": {"prompt": "0.000001", "completion": "0.000002"}, "architecture": {}},
    ]})
    with patch("httpx.AsyncClient", ctor):
        result = asyncio.run(_fetch_openrouter("key"))
    assert [m["id"] for m in result] == ["free", "cheap", "expensive"]
