"""Pins the vision-vs-text routing rule for batch_ocr_gemini — see docs/batch-ocr.md.

`_needs_vision` decides whether a document's image must be sent to Gemini (vision,
billed for image tokens) or whether the existing OCR text is good enough to send
text-only (cheaper, no image). The rule: no text at all → vision; any existing
text, regardless of which engine produced it (including local tesseract/easyocr)
→ text-only, since keeping that text implies its quality is acceptable.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
from types import SimpleNamespace

from app.services.batch_ocr import _needs_vision


def _doc(ocr_text=None, ocr_model=None):
    return SimpleNamespace(ocr_text=ocr_text, ocr_model=ocr_model)


def test_needs_vision_when_no_text():
    # Doc:  docs/batch-ocr.md — hybrid routing
    # Rule: a document with no OCR text at all must go through vision.
    assert _needs_vision(_doc(ocr_text=None)) is True
    assert _needs_vision(_doc(ocr_text="   ")) is True


def test_text_only_for_local_ocr_engines():
    # Doc:  docs/batch-ocr.md — hybrid routing
    # Rule: local-engine text (tesseract/easyocr) is reused as-is, not re-OCR'd —
    # keeping it implies the quality is already acceptable.
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="tesseract")) is False
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="easyocr")) is False


def test_text_only_when_ai_ocr_text_already_exists():
    # Doc:  docs/batch-ocr.md — hybrid routing
    # Rule: text from an AI-grade engine is reused — no image is sent.
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="mistral-ocr-latest (batch)")) is False
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="gemini-2.5-flash (batch)")) is False
