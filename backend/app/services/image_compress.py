"""Background task runner: resize large image files on disk to a maximum dimension."""
import hashlib
import io
import logging
from pathlib import Path

from PIL import Image

from ..database import SessionLocal
from ..models import Document
from .task_runtime import finish, is_stopped, log_task, set_progress

log = logging.getLogger(__name__)

# Formats we can safely read and write back with PIL
COMPRESSIBLE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp"}

# PIL save format per extension
_PIL_FORMAT: dict[str, str] = {
    ".jpg": "JPEG", ".jpeg": "JPEG",
    ".png": "PNG",
    ".tiff": "TIFF", ".tif": "TIFF",
    ".webp": "WEBP",
}


def count_compress_candidates(threshold: int) -> tuple[int, int]:
    """Return (candidates_exceeding_threshold, total_image_files).
    Uses PIL lazy-open (header-only) for speed.
    """
    db = SessionLocal()
    try:
        fps = [
            row[0] for row in db.query(Document.filepath)
            .filter(Document.is_deleted == False)
            .all()
        ]
    finally:
        db.close()

    total = 0
    over = 0
    for fp in fps:
        if not fp:
            continue
        path = Path(fp)
        if path.suffix.lower() not in COMPRESSIBLE_EXTENSIONS:
            continue
        if not path.exists():
            continue
        total += 1
        try:
            with Image.open(str(path)) as img:
                w, h = img.size
            if max(w, h) > threshold:
                over += 1
        except Exception:
            pass
    return over, total


async def run_compress_images(task_id: int, config: dict) -> None:
    max_long_side = int(config.get("max_long_side", 1024))
    log_task(task_id, f"Starting: compress images with long side > {max_long_side}px")

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(Document.is_deleted == False)
            .all()
        )
        image_docs = [
            doc for doc in docs
            if doc.filepath and Path(doc.filepath).suffix.lower() in COMPRESSIBLE_EXTENSIONS
        ]
        total = len(image_docs)
        log_task(task_id, f"Found {total} image file(s) to check")
        set_progress(task_id, 0, total)

        processed = 0
        skipped = 0
        failed = 0

        for i, doc in enumerate(image_docs):
            if is_stopped(task_id):
                log_task(task_id, f"Stopped after checking {i} file(s)")
                return

            path = Path(doc.filepath)
            if not path.exists():
                skipped += 1
                set_progress(task_id, i + 1, total)
                continue

            try:
                with Image.open(str(path)) as img:
                    w, h = img.size

                if max(w, h) <= max_long_side:
                    skipped += 1
                    set_progress(task_id, i + 1, total)
                    continue

                with Image.open(str(path)) as img:
                    img = img.convert("RGB")
                    img.thumbnail((max_long_side, max_long_side), Image.LANCZOS)
                    suffix = path.suffix.lower()
                    fmt = _PIL_FORMAT.get(suffix, "JPEG")
                    buf = io.BytesIO()
                    if fmt == "JPEG":
                        img.save(buf, format="JPEG", quality=85)
                    elif fmt == "WEBP":
                        img.save(buf, format="WEBP", quality=85)
                    else:
                        img.save(buf, format=fmt)

                new_bytes = buf.getvalue()
                path.write_bytes(new_bytes)

                new_hash = hashlib.sha256(new_bytes).hexdigest()
                doc.file_size = len(new_bytes)
                doc.file_hash = new_hash
                db.commit()

                new_w = min(w, max_long_side) if w >= h else w * max_long_side // h
                new_h = min(h, max_long_side) if h >= w else h * max_long_side // w
                processed += 1
                log_task(task_id, f"✓ {doc.filename}: {w}×{h} → ≤{max_long_side}px ({len(new_bytes):,} bytes)")
            except Exception as exc:
                failed += 1
                log_task(task_id, f"✗ {doc.filename}: {exc}", "error")
                log.exception("compress_images failed for %s", doc.filepath)

            set_progress(task_id, i + 1, total)
    finally:
        db.close()

    finish(task_id, "done", {"processed": processed, "skipped": skipped, "failed": failed})
    log_task(task_id, f"Done — compressed {processed}, skipped {skipped}, failed {failed}")
