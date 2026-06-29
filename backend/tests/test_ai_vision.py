"""Pins Mistral OCR support in AI Vision — see docs/code-map.md (ai_vision.py).

Mistral OCR is a dedicated /v1/ocr endpoint returning per-page markdown, billed
per page (not per token). These tests pin the response parsing and pricing rule.
"""
from app.services.ai_vision import (
    VISION_CAPABLE,
    VISION_DEFAULTS,
    VISION_FULL_PROMPT,
    MISTRAL_OCR_PRICE_PER_PAGE,
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
