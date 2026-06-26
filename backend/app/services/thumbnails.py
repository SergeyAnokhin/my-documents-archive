import re
from pathlib import Path
from typing import Optional
import logging

from PIL import Image

from ..config import settings

log = logging.getLogger(__name__)

THUMB_SIZE = (300, 400)


def _safe_stem(stem: str) -> str:
    """Sanitize a filename stem so it is safe to embed in a thumbnail filename."""
    s = re.sub(r"[^\w-]", "_", stem)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:40]


def get_thumbnail_path(document_id: int, filename_stem: str = "") -> Path:
    """Return the thumbnail path for a document.

    New documents use the pattern  {id}_{safe_stem}.jpg  so the file is
    human-readable in the thumbnails folder.  Existing thumbnails that were
    generated with the old  {id}.jpg  pattern are not renamed — the stored
    thumbnail_path column keeps pointing to the correct file.
    """
    thumb_dir = settings.thumbnails_dir
    thumb_dir.mkdir(parents=True, exist_ok=True)
    if filename_stem:
        safe = _safe_stem(filename_stem)
        return thumb_dir / f"{document_id}_{safe}.jpg"
    return thumb_dir / f"{document_id}.jpg"


def cleanup_orphan_thumbnails(active_thumbnail_paths: set[str]) -> int:
    """Delete .jpg files in the thumbnails dir that no active document references.

    Pass the set of thumbnail_path values from all non-deleted documents.
    Returns the number of files removed.
    """
    thumb_dir = settings.thumbnails_dir
    if not thumb_dir.exists():
        return 0
    removed = 0
    for f in thumb_dir.glob("*.jpg"):
        if str(f) not in active_thumbnail_paths:
            try:
                f.unlink()
                removed += 1
            except OSError as e:
                log.warning("Could not delete orphan thumbnail %s: %s", f, e)
    return removed


def generate_thumbnail(filepath: str, document_id: int) -> Optional[str]:
    path = Path(filepath)
    mime = path.suffix.lower()
    thumb_path = get_thumbnail_path(document_id, path.stem)

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
