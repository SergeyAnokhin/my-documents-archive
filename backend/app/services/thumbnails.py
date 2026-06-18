from pathlib import Path
from typing import Optional
import logging

from PIL import Image

from ..config import settings

log = logging.getLogger(__name__)

THUMB_SIZE = (300, 400)


def get_thumbnail_path(document_id: int) -> Path:
    thumb_dir = settings.thumbnails_dir
    thumb_dir.mkdir(parents=True, exist_ok=True)
    return thumb_dir / f"{document_id}.jpg"


def generate_thumbnail(filepath: str, document_id: int) -> Optional[str]:
    path = Path(filepath)
    mime = path.suffix.lower()
    thumb_path = get_thumbnail_path(document_id)

    try:
        if mime == ".pdf":
            return _thumbnail_from_pdf(path, thumb_path)
        else:
            return _thumbnail_from_image(path, thumb_path)
    except Exception as e:
        log.warning("Thumbnail generation failed for %s: %s", filepath, e)
        return None


def _thumbnail_from_image(src: Path, dest: Path) -> str:
    with Image.open(src) as img:
        img = img.convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        img.save(dest, "JPEG", quality=85)
    return str(dest)


def _thumbnail_from_pdf(src: Path, dest: Path) -> str:
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(str(src), first_page=1, last_page=1, dpi=100)
        if pages:
            img = pages[0].convert("RGB")
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            img.save(dest, "JPEG", quality=85)
            return str(dest)
    except Exception as e:
        log.warning("pdf2image failed, falling back to Pillow: %s", e)

    # Fallback: try Pillow directly (works for some PDFs)
    with Image.open(src) as img:
        img = img.convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        img.save(dest, "JPEG", quality=85)
    return str(dest)
