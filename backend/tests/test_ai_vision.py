"""Pins Mistral OCR support in AI Vision — see docs/code-map.md (ai_vision.py).

Mistral OCR is a dedicated /v1/ocr endpoint returning per-page markdown, billed
per page (not per token). These tests pin the response parsing and pricing rule.
"""
from app.services.ai_vision import (
    VISION_CAPABLE,
    VISION_DEFAULTS,
    MISTRAL_OCR_PRICE_PER_PAGE,
    _parse_mistral_ocr,
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
