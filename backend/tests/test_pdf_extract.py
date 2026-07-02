"""Pins native PDF text-layer extraction — see docs/code-map.md (services/pdf_extract.py).

extract_pdf_text() reads the embedded text layer of a born-digital PDF (no
OCR/rasterization) and returns None when that layer is too sparse to be
useful, so the caller (services/ocr.py) knows to fall back to OCR instead.
pypdf.PdfReader is mocked — no real PDF file is parsed.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.pdf_extract import MIN_TEXT_LENGTH, extract_pdf_text


def _mock_reader(page_texts: list[str | None]):
    pages = []
    for t in page_texts:
        page = MagicMock()
        page.extract_text.return_value = t
        pages.append(page)
    reader = MagicMock()
    reader.pages = pages
    return MagicMock(return_value=reader)


def test_extract_pdf_text_joins_pages_with_blank_line(tmp_path):
    # Rule: non-empty page text is "\n\n"-joined, matching services/ocr.py's
    #       per-page join convention.
    long_page = "x" * 60
    ctor = _mock_reader([long_page, long_page])
    with patch("pypdf.PdfReader", ctor):
        text = extract_pdf_text(str(tmp_path / "a.pdf"))
    assert text == f"{long_page}\n\n{long_page}"


def test_extract_pdf_text_drops_empty_and_none_pages(tmp_path):
    # Rule: pages with no text (None or "") are excluded from the join —
    #       e.g. a blank second page doesn't produce a stray separator.
    long_page = "y" * 60
    ctor = _mock_reader([long_page, None, "   ", long_page])
    with patch("pypdf.PdfReader", ctor):
        text = extract_pdf_text(str(tmp_path / "a.pdf"))
    assert text == f"{long_page}\n\n{long_page}"


def test_extract_pdf_text_returns_none_below_min_length(tmp_path):
    # Rule: a PDF whose extractable text is shorter than MIN_TEXT_LENGTH (e.g.
    #       a scanned page with only a stray embedded word) is treated as
    #       having no usable text layer — caller falls back to OCR.
    ctor = _mock_reader(["short title"])
    assert len("short title") < MIN_TEXT_LENGTH
    with patch("pypdf.PdfReader", ctor):
        assert extract_pdf_text(str(tmp_path / "a.pdf")) is None


def test_extract_pdf_text_propagates_reader_errors(tmp_path):
    # Rule: unreadable/corrupt/encrypted files raise — caller (services/ocr.py)
    #       catches and falls back to the OCR pipeline.
    ctor = MagicMock(side_effect=ValueError("corrupt PDF"))
    with patch("pypdf.PdfReader", ctor):
        with pytest.raises(ValueError, match="corrupt PDF"):
            extract_pdf_text(str(tmp_path / "a.pdf"))
