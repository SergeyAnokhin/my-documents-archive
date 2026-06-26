"""
OCR service — Step 1 of the indexing pipeline.

Priority:
  1. External OCR Worker (if configured and reachable)
  2. Local Tesseract (fallback / default)
"""

import io
import logging
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image

from ..config import settings

log = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────────────

async def extract_text(filepath: str) -> str:
    """Return OCR text for the given file. Raises on unrecoverable error."""
    path = Path(filepath)

    if settings.ocr_engine == "external":
        try:
            return await _external_ocr(path)
        except Exception as e:
            log.warning("External OCR failed (%s), falling back to Tesseract", e)

    return _local_tesseract(path)


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

async def _external_ocr(path: Path) -> str:
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
        return data.get("text", "")


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
