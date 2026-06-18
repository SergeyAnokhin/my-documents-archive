"""Folder watcher — auto-detects new files in documents directory.

Uses watchfiles (fast, native) to monitor data/documents/ for new files.
When a new file appears, it's automatically uploaded to the database
and indexed through the full pipeline (OCR → Vision → AI → Embeddings).
"""

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from backend.config import DOCUMENTS_DIR, SUPPORTED_FORMATS
from backend.database import SessionLocal
from backend.models import Document, generate_uuid, file_hash

logger = logging.getLogger(__name__)

# Watcher state
_watcher_thread: Optional[threading.Thread] = None
_watcher_running = False
_watcher_stats = {
    "enabled": False,
    "watched_dir": str(DOCUMENTS_DIR),
    "files_discovered": 0,
    "files_processed": 0,
    "last_event": None,
    "errors": 0,
}


def get_watcher_stats() -> dict:
    """Return current watcher status and stats."""
    return {
        **_watcher_stats,
        "running": _watcher_running,
        "thread_alive": _watcher_thread is not None and _watcher_thread.is_alive(),
    }


def _handle_new_file(file_path: Path) -> bool:
    """Register and index a newly discovered file. Returns True on success."""
    if not file_path.exists():
        return False

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        logger.debug("Watcher: skipping unsupported format %s: %s", ext, file_path.name)
        return False

    # Check if already in database (by path)
    db = SessionLocal()
    try:
        existing = db.query(Document).filter(
            Document.file_path == str(file_path.resolve())
        ).first()
        if existing:
            logger.debug("Watcher: already indexed: %s", file_path.name)
            return False

        content = file_path.read_bytes()
        fhash = file_hash(content)

        # Check hash duplicate
        existing_hash = db.query(Document).filter(
            Document.file_hash == fhash
        ).first()
        if existing_hash:
            logger.debug("Watcher: duplicate hash: %s", file_path.name)
            return False

        # Create document record
        doc_id = generate_uuid()
        stored_name = f"{doc_id}{ext}"
        stored_path = DOCUMENTS_DIR / stored_name

        # Copy file to documents dir if it's not already there
        if file_path.parent != DOCUMENTS_DIR:
            stored_path.write_bytes(content)
            file_path = stored_path

        doc = Document(
            id=doc_id,
            filename=stored_name,
            original_filename=file_path.name,
            file_path=str(file_path.resolve()),
            file_hash=fhash,
            file_size=len(content),
            mime_type=_guess_mime(ext),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Index (thumbnail + OCR + Vision + AI + Embeddings)
        from backend.indexer import index_document
        from backend.thumbnails import generate_thumbnail

        try:
            thumb_path = generate_thumbnail(file_path, doc_id)
            if thumb_path:
                doc.thumbnail_path = thumb_path
                db.commit()
        except Exception:
            pass

        index_document(doc_id)
        logger.info("Watcher: indexed new file: %s", file_path.name)
        _watcher_stats["files_processed"] += 1
        return True

    except Exception as e:
        logger.warning("Watcher: failed to process %s: %s", file_path.name, e)
        _watcher_stats["errors"] += 1
        return False
    finally:
        db.close()


def _guess_mime(ext: str) -> str:
    """Guess MIME type from file extension."""
    mime_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }
    return mime_map.get(ext, "application/octet-stream")


def _watcher_loop():
    """Background thread: watch for new files using watchfiles."""
    global _watcher_running
    _watcher_running = True
    _watcher_stats["enabled"] = True

    try:
        from watchfiles import watch

        logger.info("Watcher: monitoring %s", DOCUMENTS_DIR)
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

        for changes in watch(str(DOCUMENTS_DIR)):
            if not _watcher_running:
                break

            for change_type, file_path_str in changes:
                if not _watcher_running:
                    break

                file_path = Path(file_path_str)
                # Only process new files, not modifications
                if change_type.name in ("added", "created"):
                    _watcher_stats["files_discovered"] += 1
                    _watcher_stats["last_event"] = f"{change_type.name}: {file_path.name}"
                    _handle_new_file(file_path)

    except ImportError:
        logger.warning("watchfiles not installed — watcher disabled")
        _watcher_stats["enabled"] = False
    except Exception as e:
        logger.error("Watcher error: %s", e)
        _watcher_stats["errors"] += 1
    finally:
        _watcher_running = False
        _watcher_stats["enabled"] = False


def start_watcher() -> bool:
    """Start the folder watcher in a background thread. Returns True if started."""
    global _watcher_thread, _watcher_running

    if _watcher_running:
        return False

    _watcher_running = True
    _watcher_thread = threading.Thread(
        target=_watcher_loop,
        name="docintel-watcher",
        daemon=True,
    )
    _watcher_thread.start()
    logger.info("Watcher started")
    return True


def stop_watcher() -> bool:
    """Stop the folder watcher. Returns True if was running."""
    global _watcher_running

    if not _watcher_running:
        return False

    _watcher_running = False
    logger.info("Watcher stopped")
    return True
