"""Pins DB backup list + restore — see docs/code-map.md (services/db_backup.py)
and docs/api.md §Admin (`/api/admin/backups`, `/api/admin/backups/restore`).

Restore must reject anything outside the backup dir or not matching the prefix
(path-traversal guard), and must round-trip a real SQLite file while keeping a
pre-restore safety snapshot.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import sqlite3

import pytest

from app.config import settings
from app.services import db_backup


def _make_sqlite(path, value):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES (?)", (value,))
    con.commit()
    con.close()


def test_list_and_restore_roundtrip(tmp_path, monkeypatch):
    # Doc:  docs/api.md §Admin — GET /api/admin/backups (list) and
    #       POST /api/admin/backups/restore ("saves a docintell.db.pre-restore copy
    #       first"); docs/code-map.md → db_backup.py ("restore = atomic swap +
    #       pre-restore safety snapshot").
    # Rule: list returns the backup; restore swaps it live and writes a pre-restore snapshot.
    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))

    db = tmp_path / ".docintell" / "docintell.db"
    db.parent.mkdir(parents=True)
    _make_sqlite(db, "old")
    _make_sqlite(tmp_path / "docintell.db.backup.1", "new")

    assert [b["name"] for b in db_backup.list_backups()] == ["docintell.db.backup.1"]

    db_backup.restore_backup("docintell.db.backup.1")

    con = sqlite3.connect(str(db))
    try:
        assert con.execute("SELECT v FROM t").fetchone()[0] == "new"
    finally:
        con.close()
    assert (tmp_path / ".docintell" / "docintell.db.pre-restore").exists()


def test_restore_rejects_path_traversal(tmp_path, monkeypatch):
    # Doc:  docs/api.md §Admin — restore is "400 on unknown/invalid name". This pins
    #       the underlying guard (docs/code-map.md → db_backup.py) that the router
    #       surfaces as a 400.
    # Rule: a name escaping the backup dir or not matching the backup prefix is rejected.
    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))

    with pytest.raises(ValueError):
        db_backup.restore_backup("../evil.db")        # escapes the backup dir
    with pytest.raises(ValueError):
        db_backup.restore_backup("not-a-backup.db")   # wrong prefix


def test_create_backup_respects_appsettings_keep_over_env(tmp_path, monkeypatch):
    # Doc:  docs/code-map.md → db_backup.py ("keep is an AppSettings row, overriding
    #       BACKUP_KEEP"). Frontend Backup tab writes this row via PATCH /backups/keep.
    # Rule: an AppSettings "backup_keep" row takes priority over the BACKUP_KEEP env var,
    #       and old snapshots past the new (lower) keep count are pruned.
    from app.database import Base, get_engine
    from app.models import AppSettings

    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_KEEP", "5")  # should be overridden by the DB setting

    db_file = tmp_path / ".docintell" / "docintell.db"
    db_file.parent.mkdir(parents=True)
    _make_sqlite(db_file, "live")
    # Pre-existing snapshots at .3/.4 must be pruned once keep=2 applies.
    for n in (1, 2, 3, 4):
        _make_sqlite(tmp_path / f"docintell.db.backup.{n}", f"old{n}")

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import Session
    db = Session(bind=engine)
    try:
        db.add(AppSettings(key="backup_keep", value="2"))
        db.commit()

        db_backup.create_backup(db)
    finally:
        db.close()

    names = sorted(p.name for p in tmp_path.glob("docintell.db.backup.*"))
    assert names == ["docintell.db.backup.1", "docintell.db.backup.2"]
