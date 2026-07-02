"""Periodic SQLite backup sidecar.

Runs next to the backend in the same pod. Every BACKUP_INTERVAL_SECONDS it checks
whether the DB changed since the last backup and, if so, writes a consistent copy
to the NAS document root (BACKUP_DIR), rotating so only the newest N copies are
kept:  <prefix>.1 = newest, <prefix>.2 = previous, ...

- The DB lives on the fast local-path PVC; backups go to the SMB/NAS root.
- Uses the sqlite3 online backup API, so the copy is consistent even while the
  app is writing (no need to stop the backend).
- "after each change, at most once per interval": the loop sleeps the full
  interval, then backs up only if the DB changed -> never more than once per
  interval, and an unchanged DB is skipped.
- How many copies to keep (N) is read fresh from the `app_settings` table
  (row `backup_keep`, set from the admin Backup tab) on every run, falling
  back to the BACKUP_KEEP env var if that row is missing or unreadable.
"""

import logging
import os
import pathlib
import sqlite3
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s backup %(levelname)s %(message)s")
log = logging.getLogger("backup")

LIBRARY = os.environ.get("LIBRARY_PATH", "/data/library")
DB = pathlib.Path(LIBRARY) / ".docintell" / "docintell.db"
DEST_DIR = pathlib.Path(os.environ.get("BACKUP_DIR", LIBRARY))
INTERVAL = int(os.environ.get("BACKUP_INTERVAL_SECONDS", "300"))
KEEP_ENV_DEFAULT = max(1, int(os.environ.get("BACKUP_KEEP", "2")))
KEEP_MIN, KEEP_MAX = 1, 30
PREFIX = os.environ.get("BACKUP_PREFIX", "docintell.db.backup")


def _current_keep() -> int:
    """Read backup_keep from app_settings (set via the admin Backup tab); falls
    back to KEEP_ENV_DEFAULT if the row is missing, unreadable, or invalid."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM app_settings WHERE key = 'backup_keep'").fetchone()
        finally:
            con.close()
        if row and row[0]:
            return max(KEEP_MIN, min(KEEP_MAX, int(row[0])))
    except Exception:
        pass
    return KEEP_ENV_DEFAULT


def _prune_beyond(keep: int) -> None:
    """Delete any numbered snapshot past the current keep count (e.g. left over
    after the admin lowers the setting)."""
    for p in DEST_DIR.glob(f"{PREFIX}.*"):
        suffix = p.name[len(PREFIX) + 1:]
        if suffix.isdigit() and int(suffix) > keep:
            p.unlink()


def signature() -> tuple | None:
    """Identity of the current DB state. Includes the -wal file in case WAL mode
    is ever enabled (default journal mode touches the main file directly)."""
    sig = []
    for suffix in ("", "-wal"):
        p = DB.with_name(DB.name + suffix)
        if p.exists():
            st = p.stat()
            sig.append((suffix, st.st_mtime_ns, st.st_size))
    return tuple(sig) if sig else None


def do_backup() -> None:
    keep = _current_keep()
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DEST_DIR / f"{PREFIX}.tmp"
    if tmp.exists():
        tmp.unlink()

    # Consistent online backup (works while the backend writes).
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    # Rotate: drop oldest, shift the rest up by one, new copy becomes .1
    oldest = DEST_DIR / f"{PREFIX}.{keep}"
    if oldest.exists():
        oldest.unlink()
    for i in range(keep - 1, 0, -1):
        cur = DEST_DIR / f"{PREFIX}.{i}"
        if cur.exists():
            cur.rename(DEST_DIR / f"{PREFIX}.{i + 1}")
    tmp.rename(DEST_DIR / f"{PREFIX}.1")
    _prune_beyond(keep)
    log.info("backup written to %s.1 (rotated, keep=%d)", PREFIX, keep)


def main() -> None:
    log.info("db-backup started: db=%s dest=%s interval=%ss keep=%d (default)", DB, DEST_DIR, INTERVAL, KEEP_ENV_DEFAULT)
    last = None
    while True:
        time.sleep(INTERVAL)
        try:
            sig = signature()
            if sig is None:
                log.warning("db not found yet: %s", DB)
            elif sig == last:
                log.info("no change since last backup; skipping")
            else:
                do_backup()
                last = sig
        except Exception:
            log.exception("backup failed")


if __name__ == "__main__":
    main()
