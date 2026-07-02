"""
Native PDF text-layer extraction — no OCR involved, for born-digital PDFs
(e.g. contracts exported from Word) that already carry a text layer.

Used by services/ocr.py as a fast-path before falling back to
rasterize-and-OCR for scanned/image-only PDFs: reading the embedded text
layer directly is faster and more accurate than OCR, and naturally covers
every page (no per-page image/DPI cost to worry about).
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Below this many characters, treat the PDF as scanned/image-only (no usable
# text layer) and let the caller fall back to OCR instead.
MIN_TEXT_LENGTH = 100


def extract_pdf_text(filepath: str) -> str | None:
    """Return the embedded text layer of a PDF, or None if it has no usable one.

    Raises on unreadable/corrupt/encrypted files — caller (services/ocr.py)
    is responsible for catching and falling back to the OCR pipeline.
    """
    from pypdf import PdfReader

    reader = PdfReader(Path(filepath))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(p for p in pages if p)

    if len(text) < MIN_TEXT_LENGTH:
        return None
    return text
