"""
Folder watcher service (Phase 5).

Watches enabled WatchedFolder entries using watchdog.
On new file: registers in DB and queues the full indexing pipeline.
Start/stop via FolderWatcher.start() / .stop().
Call FolderWatcher.reload() after any folder CRUD.
"""

import asyncio
import logging
import threading
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from ..database import SessionLocal
from ..models import Document, WatchedFolder
from .storage import SUPPORTED_EXTENSIONS, compute_file_hash, guess_mime
from .thumbnails import generate_thumbnail

log = logging.getLogger(__name__)


def _wait_for_file(path: Path, timeout: float = 10.0) -> bool:
    """Block until a file stops growing (fully written). Returns False on timeout."""
    deadline = time.monotonic() + timeout
    last_size = -1
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
            if size > 0 and size == last_size:
                return True
            last_size = size
        except OSError:
            pass
        time.sleep(0.5)
    return last_size > 0


def _pick_up_file(path: Path) -> None:
    """Register a new file in the DB and queue the indexing pipeline."""
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return
    if not _wait_for_file(path):
        log.warning("Watcher: file not ready after timeout: %s", path)
        return

    db = SessionLocal()
    try:
        # Skip already-known files
        if db.query(Document).filter(
            Document.filepath == str(path),
            Document.is_deleted == False,
        ).first():
            return
        file_hash = compute_file_hash(path)
        if db.query(Document).filter(Document.file_hash == file_hash).first():
            return

        mime = guess_mime(path)
        doc = Document(
            filename=path.name,
            filepath=str(path),
            file_hash=file_hash,
            file_size=path.stat().st_size,
            mime_type=mime,
        )
        db.add(doc)
        db.flush()
        thumb = generate_thumbnail(str(path), doc.id)
        if thumb:
            doc.thumbnail_path = thumb
        db.commit()
        doc_id = doc.id
        log.info("Watcher: picked up %s (id=%s)", path.name, doc_id)
    except Exception:
        log.exception("Watcher: failed to register %s", path)
        db.rollback()
        return
    finally:
        db.close()

    # Run indexing in this thread using a fresh event loop
    try:
        from .indexer import index_document
        asyncio.run(index_document(doc_id))
    except Exception:
        log.exception("Watcher: indexing failed for %s", path)


class _FolderHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        threading.Thread(
            target=_pick_up_file,
            args=(Path(event.src_path),),
            daemon=True,
        ).start()

    def on_moved(self, event):
        """Handle files moved/renamed into the watched directory."""
        if event.is_directory:
            return
        threading.Thread(
            target=_pick_up_file,
            args=(Path(event.dest_path),),
            daemon=True,
        ).start()


class FolderWatcher:
    def __init__(self):
        self._observer = Observer()
        self._watches: dict[int, object] = {}
        self._handler = _FolderHandler()

    def start(self) -> None:
        self._load_from_db()
        self._observer.start()
        log.info("Folder watcher started (%d folder(s))", len(self._watches))

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        log.info("Folder watcher stopped")

    def reload(self) -> None:
        """Re-sync watches from DB after folder add/toggle/delete."""
        db = SessionLocal()
        try:
            enabled = {
                f.id: f.path
                for f in db.query(WatchedFolder).filter(WatchedFolder.enabled == True).all()
            }
        finally:
            db.close()

        # Unschedule removed/disabled folders
        for fid in list(self._watches):
            if fid not in enabled:
                self._observer.unschedule(self._watches.pop(fid))
                log.info("Watcher: stopped watching folder id=%d", fid)

        # Schedule new folders
        for fid, path in enabled.items():
            if fid not in self._watches:
                self._add_watch(fid, path)

    def _load_from_db(self) -> None:
        db = SessionLocal()
        try:
            for f in db.query(WatchedFolder).filter(WatchedFolder.enabled == True).all():
                self._add_watch(f.id, f.path)
        finally:
            db.close()

    def _add_watch(self, folder_id: int, path: str) -> None:
        p = Path(path)
        if not p.exists():
            log.warning("Watcher: folder not found, skipping: %s", path)
            return
        watch = self._observer.schedule(self._handler, str(p), recursive=False)
        self._watches[folder_id] = watch
        log.info("Watcher: watching %s", path)


watcher = FolderWatcher()
