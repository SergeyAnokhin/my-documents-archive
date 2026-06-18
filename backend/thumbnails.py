"""Thumbnail generation for documents."""

import logging
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from backend.config import THUMBNAILS_DIR

logger = logging.getLogger(__name__)

THUMB_SIZE = (300, 400)  # 3:4 aspect


def generate_thumbnail(file_path: Path, doc_id: str) -> str:
    """Generate a thumbnail for a document. Returns path to thumbnail file."""
    thumb_name = f"{doc_id}_thumb.jpg"
    thumb_path = THUMBNAILS_DIR / thumb_name

    if thumb_path.exists():
        return str(thumb_path)

    suffix = file_path.suffix.lower()

    try:
        if suffix == ".pdf":
            return _pdf_thumbnail(file_path, thumb_path)
        else:
            return _image_thumbnail(file_path, thumb_path)
    except Exception as e:
        logger.warning("Thumbnail generation failed for %s: %s", file_path, e)
        return ""


def _pdf_thumbnail(pdf_path: Path, thumb_path: Path) -> str:
    """Generate thumbnail from first page of PDF."""
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        pix = page.get_pixmap(dpi=72)  # Low DPI for thumbnail
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        img.save(thumb_path, "JPEG", quality=80)
        return str(thumb_path)
    finally:
        doc.close()


def _image_thumbnail(img_path: Path, thumb_path: Path) -> str:
    """Generate thumbnail from image."""
    img = Image.open(img_path)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.thumbnail(THUMB_SIZE, Image.LANCZOS)
    img.save(thumb_path, "JPEG", quality=80)
    return str(thumb_path)
