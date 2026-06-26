"""Pins DB backup list + restore — see docs/code-map.md (services/db_backup.py).

Restore must reject anything outside the backup dir or not matching the prefix
(path-traversal guard), and must round-trip a real SQLite file while keeping a
pre-restore safety snapshot.
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
    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))

    with pytest.raises(ValueError):
        db_backup.restore_backup("../evil.db")        # escapes the backup dir
    with pytest.raises(ValueError):
        db_backup.restore_backup("not-a-backup.db")   # wrong prefix
