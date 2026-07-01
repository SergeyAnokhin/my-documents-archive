"""Pins Mistral OCR support and vision-provider request construction — see
docs/code-map.md (ai_vision.py).

Mistral OCR is a dedicated /v1/ocr endpoint returning per-page markdown, billed
per page (not per token). These tests pin the response parsing and pricing rule,
plus the outbound request shape for all three vision call paths
(_call_openai_compat / _call_mistral_ocr / _call_gemini) — mocked at the SDK/HTTP
boundary (openai.AsyncOpenAI, httpx.AsyncClient, google.genai.Client) so no real,
billable request is ever made.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_common import SyntheticProvider
from app.services.ai_vision import (
    VISION_CAPABLE,
    VISION_DEFAULTS,
    VISION_FULL_PROMPT,
    MISTRAL_OCR_PRICE_PER_PAGE,
    VisionFullResponse,
    _call_gemini,
    _call_mistral_ocr,
    _call_openai_compat,
    parse_mistral_ocr as _parse_mistral_ocr,
    parse_vision_full as _parse_vision_full,
)
from app.services.provider_models import _mistral_ocr_models


def test_mistral_is_vision_capable():
    assert "mistral" in VISION_CAPABLE
    assert VISION_DEFAULTS["mistral"] == "mistral-ocr-latest"


def test_parse_mistral_ocr_joins_pages_and_prices_per_page():
    data = {
        "pages": [{"markdown": "page one"}, {"markdown": "page two"}],
        "usage_info": {"pages_processed": 2},
    }
    text, cost = _parse_mistral_ocr(data)
    assert text == "page one\n\npage two"
    assert cost == 2 * MISTRAL_OCR_PRICE_PER_PAGE


def test_parse_mistral_ocr_defaults_to_one_page():
    text, cost = _parse_mistral_ocr({"pages": [{"markdown": "x"}]})
    assert text == "x"
    assert cost == MISTRAL_OCR_PRICE_PER_PAGE


def test_mistral_model_list_surfaces_ocr_for_vision():
    models = _mistral_ocr_models()
    assert any(m["id"] == "mistral-ocr-latest" and m["supports_vision"] for m in models)


# ── Combined vision+analysis parsing (VISION_FULL_PROMPT) ──────────────────────

def test_vision_full_prompt_shares_document_taxonomy():
    # Rule: the vision prompt is built from the same DOCUMENT_TYPES_BLOCK as the
    # text-analysis prompt, so the two type lists never drift.
    assert "passport" in VISION_FULL_PROMPT
    assert "unclassified" in VISION_FULL_PROMPT


def test_parse_vision_full_strips_code_fence_and_returns_dict():
    # Rule: a ```json … ``` fence is stripped; a JSON object → dict.
    raw = '```json\n{"text": "hello", "document_type": "invoice"}\n```'
    data = _parse_vision_full(raw)
    assert data["text"] == "hello"
    assert data["document_type"] == "invoice"


def test_parse_vision_full_returns_none_on_garbage_or_non_object():
    # Rule: non-JSON or a non-object (e.g. a JSON array) → None, so the caller
    # falls back to treating the response as plain transcription.
    assert _parse_vision_full("not json at all") is None
    assert _parse_vision_full("[1, 2, 3]") is None


# ── _call_openai_compat: request construction ───────────────────────────────────

def _mock_openai_client(content: str = "{}", tin: int = 10, tout: int = 5):
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=tin, completion_tokens=tout),
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    ctor = MagicMock(return_value=client)
    return ctor, client


def test_call_openai_compat_uses_vision_default_model():
    # Doc:  docs/code-map.md → services/ai_vision.py — VISION_DEFAULTS
    # Rule: with no provider.model set, the per-type VISION_DEFAULTS model is used.
    provider = SyntheticProvider(name="oa", provider_type="openai", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compat(provider, "YmFzZTY0", "describe this"))

    assert client.chat.completions.create.call_args.kwargs["model"] == VISION_DEFAULTS["openai"]


def test_call_openai_compat_sends_image_and_prompt_content_blocks():
    # Doc:  docs/code-map.md → services/ai_vision.py
    # Rule: the user message content is [image_url data-URI, text prompt], in order.
    provider = SyntheticProvider(name="oa", provider_type="openai", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compat(provider, "YmFzZTY0", "describe this"))

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    content = messages[0]["content"]
    assert content[0] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,YmFzZTY0"}}
    assert content[1] == {"type": "text", "text": "describe this"}


def test_call_openai_compat_applies_extra_params_max_tokens_and_temperature():
    # Doc:  docs/code-map.md → components/admin/tabs/ai/ProviderSettingsPanel.tsx
    #       (per-provider temperature/max_tokens fine-tuning)
    # Rule: extra_params.max_tokens/temperature override the request defaults.
    provider = SyntheticProvider(
        name="oa", provider_type="openai", api_key="k",
        extra_params={"max_tokens": 777, "temperature": 0.3},
    )
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compat(provider, "b64", "p"))

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == 777
    assert kwargs["temperature"] == 0.3


def test_call_openai_compat_default_max_tokens_without_extra_params():
    # Doc:  none — pins the documented "2048" default in ai_vision.py
    # Rule: no extra_params → max_tokens defaults to 2048, no temperature key sent.
    provider = SyntheticProvider(name="oa", provider_type="openai", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compat(provider, "b64", "p"))

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == 2048
    assert "temperature" not in kwargs


def test_call_openai_compat_json_mode_sets_response_format():
    # Doc:  none — pins the json_mode → response_format branch
    # Rule: json_mode=True adds response_format=json_object; omitted when False.
    provider = SyntheticProvider(name="or", provider_type="openrouter", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compat(provider, "b64", "p", json_mode=True))
    assert client.chat.completions.create.call_args.kwargs["response_format"] == {"type": "json_object"}

    ctor2, client2 = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor2):
        asyncio.run(_call_openai_compat(provider, "b64", "p", json_mode=False))
    assert "response_format" not in client2.chat.completions.create.call_args.kwargs


def test_call_openai_compat_openrouter_uses_documented_base_url_default():
    # Doc:  docs/code-map.md → AI providers (base_url per provider_type)
    # Rule: openrouter's base_url defaults to the OpenRouter API root.
    provider = SyntheticProvider(name="or", provider_type="openrouter", api_key="k")
    ctor, client = _mock_openai_client()
    with patch("openai.AsyncOpenAI", ctor):
        asyncio.run(_call_openai_compat(provider, "b64", "p"))
    assert ctor.call_args.kwargs["base_url"] == "https://openrouter.ai/api/v1"


# ── _call_mistral_ocr: request construction ─────────────────────────────────────

def _mock_httpx_post(json_data: dict):
    """Fake httpx.AsyncClient() context manager whose .post() returns json_data."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctor = MagicMock(return_value=ctx)
    return ctor, client


def test_call_mistral_ocr_posts_documented_endpoint_and_payload():
    # Doc:  docs/code-map.md → services/ai_vision.py (Mistral OCR dedicated endpoint)
    # Rule: POSTs to /v1/ocr with Bearer auth and {model, document, include_image_base64}.
    provider = SyntheticProvider(
        name="m", provider_type="mistral", api_key="secret-key",
        extra_params={"include_image_base64": True},
    )
    ctor, client = _mock_httpx_post({"pages": [{"markdown": "hi"}], "usage_info": {"pages_processed": 1}})
    with patch("httpx.AsyncClient", ctor):
        asyncio.run(_call_mistral_ocr(provider, b"fakebytes"))

    call = client.post.call_args
    assert call.args[0] == "https://api.mistral.ai/v1/ocr"
    assert call.kwargs["headers"] == {"Authorization": "Bearer secret-key"}
    body = call.kwargs["json"]
    assert body["model"] == VISION_DEFAULTS["mistral"]
    assert body["document"]["type"] == "image_url"
    assert body["document"]["image_url"].startswith("data:image/jpeg;base64,")
    assert body["include_image_base64"] is True


def test_call_mistral_ocr_applies_image_policy_from_extra_params():
    # Doc:  docs/code-map.md → services/ai_vision.py parse_mistral_ocr()
    # Rule: extra_params.image_policy="strip" removes image refs from the joined text.
    provider = SyntheticProvider(name="m", provider_type="mistral", api_key="k", extra_params={"image_policy": "strip"})
    ctor, client = _mock_httpx_post({
        "pages": [{"markdown": "before ![img](url) after"}],
        "usage_info": {"pages_processed": 1},
    })
    with patch("httpx.AsyncClient", ctor):
        text, tin, tout, cost = asyncio.run(_call_mistral_ocr(provider, b"x"))

    assert "![img]" not in text
    assert "before" in text and "after" in text
    assert (tin, tout) == (0, 0)
    assert cost == MISTRAL_OCR_PRICE_PER_PAGE


def test_call_mistral_ocr_default_policy_is_placeholder():
    # Doc:  docs/code-map.md → services/ai_vision.py parse_mistral_ocr()
    # Rule: without extra_params, image refs become the "[изображение]" placeholder.
    provider = SyntheticProvider(name="m", provider_type="mistral", api_key="k")
    ctor, client = _mock_httpx_post({
        "pages": [{"markdown": "![img](url)"}],
        "usage_info": {"pages_processed": 3},
    })
    with patch("httpx.AsyncClient", ctor):
        text, _, _, cost = asyncio.run(_call_mistral_ocr(provider, b"x"))

    assert text == "[изображение]"
    assert cost == 3 * MISTRAL_OCR_PRICE_PER_PAGE


# ── _call_gemini (vision): request construction ─────────────────────────────────

def _mock_gemini_client(text: str = "{}", tin: int = 10, tout: int = 5):
    resp = SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=tin, candidates_token_count=tout),
    )
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=resp)
    ctor = MagicMock(return_value=client)
    return ctor, client


def test_call_gemini_vision_uses_default_model_and_sends_prompt_plus_image():
    # Doc:  docs/code-map.md → services/ai_vision.py — VISION_DEFAULTS
    # Rule: default model "gemini-2.5-flash"; contents = [prompt, image_part].
    provider = SyntheticProvider(name="g", provider_type="gemini", api_key="k")
    ctor, client = _mock_gemini_client()
    with patch("google.genai.Client", ctor):
        asyncio.run(_call_gemini(provider, b"imgbytes", "describe this"))

    call = client.aio.models.generate_content.call_args.kwargs
    assert call["model"] == VISION_DEFAULTS["gemini"]
    assert call["contents"][0] == "describe this"


def test_call_gemini_vision_response_schema_takes_precedence_over_json_mode():
    # Doc:  services/ai_vision.py — describe_document() passes VisionFullResponse
    #       as response_schema for structured vision+analysis output.
    # Rule: when response_schema is given, it's set on the config regardless of
    #       json_mode, and response_mime_type is not separately forced.
    provider = SyntheticProvider(name="g", provider_type="gemini", api_key="k")
    ctor, client = _mock_gemini_client()
    with patch("google.genai.Client", ctor):
        asyncio.run(_call_gemini(provider, b"x", "p", json_mode=True, response_schema=VisionFullResponse))

    cfg = client.aio.models.generate_content.call_args.kwargs["config"]
    assert cfg.response_schema is VisionFullResponse


def test_call_gemini_vision_applies_extra_params_max_tokens_and_temperature():
    # Doc:  docs/code-map.md → ProviderSettingsPanel.tsx (per-provider tuning)
    # Rule: extra_params.max_tokens/temperature flow into GenerateContentConfig.
    provider = SyntheticProvider(
        name="g", provider_type="gemini", api_key="k",
        extra_params={"max_tokens": 999, "temperature": 0.7},
    )
    ctor, client = _mock_gemini_client()
    with patch("google.genai.Client", ctor):
        asyncio.run(_call_gemini(provider, b"x", "p"))

    cfg = client.aio.models.generate_content.call_args.kwargs["config"]
    assert cfg.max_output_tokens == 999
    assert cfg.temperature == 0.7
