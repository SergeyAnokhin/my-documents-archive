"""List and restore SQLite DB backups created by the backup sidecar.

Backups live in the document root (BACKUP_DIR, defaults to the library root) as
``<prefix>.1`` (newest), ``<prefix>.2`` (previous), … The sidecar (`backup.py`)
writes them; here an advanced user can list them and restore one from the UI.

Restore is done with the sqlite3 online backup API into a temp file, then an
atomic ``os.replace`` over the live DB — and a ``docintell.db.pre-restore``
safety snapshot is taken first, so a restore is reversible.

How many snapshots to retain (``keep``) is an AppSettings row (``backup_keep``,
set from the Backup tab), overriding the ``BACKUP_KEEP`` env var default. The
sidecar reads the same AppSettings row directly (see `backend/backup.py`).
"""
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..database import engine

PREFIX = os.environ.get("BACKUP_PREFIX", "docintell.db.backup")
KEEP_MIN, KEEP_MAX = 1, 30


def _backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", settings.library_path))


def list_backups() -> list[dict]:
    d = _backup_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in d.glob(f"{PREFIX}.*"):
        if p.suffix == ".tmp" or not p.is_file():
            continue
        st = p.stat()
        out.append({
            "name": p.name,
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    out.sort(key=lambda x: x["modified"], reverse=True)  # newest first
    return out


def get_keep_count(db: Session | None = None) -> int:
    """Number of newest backups to retain. AppSettings ``backup_keep`` takes
    priority over the ``BACKUP_KEEP`` env var; clamped to [KEEP_MIN, KEEP_MAX]."""
    if db is not None:
        from ..models import AppSettings
        row = db.query(AppSettings).filter(AppSettings.key == "backup_keep").first()
        if row and row.value:
            try:
                return max(KEEP_MIN, min(KEEP_MAX, int(row.value)))
            except (ValueError, TypeError):
                pass
    return max(KEEP_MIN, min(KEEP_MAX, int(os.environ.get("BACKUP_KEEP", "2"))))


def _prune_beyond(d: Path, keep: int) -> None:
    """Delete any numbered snapshot past the current keep count (e.g. left over
    after the admin lowers the setting)."""
    for p in d.glob(f"{PREFIX}.*"):
        suffix = p.name[len(PREFIX) + 1:]
        if suffix.isdigit() and int(suffix) > keep:
            p.unlink()


def _sqlite_copy(src: Path, dst: Path) -> None:
    """Consistent page-level copy of a SQLite DB (works on a live source)."""
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        d = sqlite3.connect(str(dst))
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def create_backup(db: Session | None = None) -> dict:
    d = _backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    db_path = Path(settings.db_path)
    if not db_path.exists():
        raise FileNotFoundError("Database file not found")

    keep = get_keep_count(db)

    # Write to a local tmp (state PVC) first — SQLite file locking fails on SMB mounts.
    # After the consistent copy is done, move it to the NAS destination as a plain file.
    local_tmp = db_path.parent / f"{PREFIX}.creating"
    if local_tmp.exists():
        local_tmp.unlink()
    try:
        _sqlite_copy(db_path, local_tmp)
        oldest = d / f"{PREFIX}.{keep}"
        if oldest.exists():
            oldest.unlink()
        for i in range(keep - 1, 0, -1):
            cur = d / f"{PREFIX}.{i}"
            if cur.exists():
                cur.rename(d / f"{PREFIX}.{i + 1}")
        shutil.copy2(local_tmp, d / f"{PREFIX}.1")
        _prune_beyond(d, keep)
    finally:
        if local_tmp.exists():
            local_tmp.unlink()
    return {"created": f"{PREFIX}.1"}


def restore_backup(name: str) -> dict:
    d = _backup_dir()
    src = (d / name).resolve()
    # Path-traversal guard: must be a real backup file directly inside the dir.
    if src.parent != d.resolve() or not src.name.startswith(PREFIX) or not src.is_file():
        raise ValueError("Unknown backup file")

    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Drop pooled connections so the file is not held open during the swap.
    engine.dispose()

    # Reversible: snapshot the current DB before overwriting it.
    if db_path.exists():
        _sqlite_copy(db_path, db_path.with_name("docintell.db.pre-restore"))

    # Materialize the backup into a temp file, drop stale journal siblings,
    # then atomically swap it in as the live DB.
    tmp = db_path.with_name("docintell.db.restoring")
    if tmp.exists():
        tmp.unlink()
    _sqlite_copy(src, tmp)
    for suffix in ("-wal", "-shm", "-journal"):
        sib = db_path.with_name(db_path.name + suffix)
        if sib.exists():
            sib.unlink()
    os.replace(tmp, db_path)
    return {"restored": name}
