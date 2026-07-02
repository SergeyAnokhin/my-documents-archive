"""
OCR service — Step 1 of the indexing pipeline.

Default priority (env-var based, backwards-compat):
  1. External OCR Worker / EasyOCR (if ocr_engine="external")
  2. Local Tesseract (fallback / default)

When `engines` is passed explicitly (DB-configured priority list), engines are
tried in that order and the first one that succeeds wins.
"""

import logging
from pathlib import Path

import httpx
from PIL import Image

from ..config import settings
from .pdf_extract import extract_pdf_text

log = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────────────

async def extract_text(filepath: str, engines: list[str] | None = None) -> tuple[str, str]:
    """Return (text, engine) for the file.

    For a PDF with a usable embedded text layer (born-digital, e.g. a contract
    exported from Word), that text is returned directly as ("native") — no
    rasterize+OCR needed. Scanned/image-only PDFs fall through to the OCR
    engines below, same as before.

    engines: ordered list of engine names to try — "easyocr" | "tesseract".
    When None, falls back to settings.ocr_engine env-var behaviour (backwards compat).
    Raises when all engines fail or none are configured.
    """
    path = Path(filepath)

    if path.suffix.lower() == ".pdf":
        try:
            native_text = extract_pdf_text(filepath)
        except Exception as e:
            log.warning("Native PDF text extraction failed for %s: %s", path, e)
            native_text = None
        if native_text is not None:
            return native_text, "native"

    if engines is None:
        # Legacy env-var path
        if settings.ocr_engine == "external":
            try:
                return await _external_ocr(path)
            except Exception as e:
                log.warning("External OCR failed (%s), falling back to Tesseract", e)
        return _local_tesseract(path), "tesseract"

    # DB-configured priority — try each engine in order
    last_exc: Exception | None = None
    for engine in engines:
        if engine == "easyocr":
            try:
                return await _external_ocr(path)
            except Exception as e:
                log.warning("EasyOCR failed (%s), trying next engine", e)
                last_exc = e
        elif engine == "tesseract":
            try:
                return _local_tesseract(path), "tesseract"
            except Exception as e:
                log.warning("Tesseract failed (%s), trying next engine", e)
                last_exc = e

    raise last_exc or ValueError("No OCR engines configured")


# ── Local Tesseract ───────────────────────────────────────────────────────────

def _local_tesseract(path: Path) -> str:
    import pytesseract

    images = _to_pil_images(path)
    if not images:
        raise ValueError(f"Cannot load images from {path}")

    pages: list[str] = []
    for img in images:
        text = pytesseract.image_to_string(img, lang=settings.ocr_languages)
        pages.append(text.strip())

    return "\n\n".join(p for p in pages if p)


def _to_pil_images(path: Path) -> list[Image.Image]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_to_images(path)
    try:
        img = Image.open(path)
        img.load()
        return [img.convert("RGB")]
    except Exception as e:
        log.warning("Pillow cannot open %s: %s", path, e)
        return []


def _pdf_to_images(path: Path) -> list[Image.Image]:
    try:
        from pdf2image import convert_from_path
        return convert_from_path(str(path), dpi=200)
    except Exception as e:
        log.warning("pdf2image failed for %s: %s — trying Pillow", path, e)
        try:
            img = Image.open(path).convert("RGB")
            return [img]
        except Exception:
            return []


# ── External OCR Worker ───────────────────────────────────────────────────────

async def _external_ocr(path: Path) -> tuple[str, str]:
    url = f"{settings.external_ocr_url.rstrip('/')}/ocr"
    async with httpx.AsyncClient(timeout=120) as client:
        with open(path, "rb") as fh:
            resp = await client.post(
                url,
                files={"file": (path.name, fh, _mime_for(path))},
                params={"engine": "auto", "languages": settings.ocr_languages},
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("text", ""), (data.get("engine") or "easyocr")


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tiff": "image/tiff", ".tif": "image/tiff",
        ".heic": "image/heic", ".heif": "image/heif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
