"""Pins quality-filter behavior for single-character tags.

Doc: docs/api.md (Search quality filters) and docs/code-map.md
(services/task_runners.py: fix_quality delegates analysis gaps to Gemini Batch).
Rule: documents with any one-character tag must be exposed as a dedicated
quality gap, excluded from the "complete" filter, and re-dispatched through
Gemini Batch Analysis via explicit doc_ids.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Document
from app.routers import search as search_router
from app.services import task_runners as tasks_module


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(tasks_module, "SessionLocal", TestSessionLocal)
    yield TestSessionLocal


def _add_doc(SessionLocal, **kwargs) -> int:
    db = SessionLocal()
    defaults = {
        "filename": kwargs.get("filename", "doc.pdf"),
        "filepath": f"/lib/{kwargs.get('filename', 'doc.pdf')}-{id(kwargs)}",
        "ocr_status": "done",
        "analysis_status": "done",
        "summary": "summary",
        "document_type": "invoice",
        "tags": [],
    }
    defaults.update(kwargs)
    doc = Document(**defaults)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    doc_id = doc.id
    db.close()
    return doc_id


def test_single_char_tag_quality_filter_counts_and_excludes_from_complete(db_session):
    # Doc: docs/api.md §Search quality filter values.
    # Rule: any document with at least one 1-character tag appears in the new
    #       single_char_tag filter and no longer qualifies as "complete".
    flagged_id = _add_doc(db_session, filename="flagged.pdf", tags=["a", "passport"])
    clean_id = _add_doc(db_session, filename="clean.pdf", tags=["passport"])
    _add_doc(db_session, filename="empty.pdf", tags=[])

    db = db_session()
    flagged = search_router.search_documents(
        query="",
        mode="fulltext",
        quality="single_char_tag",
        page=1,
        page_size=24,
        db=db,
    )
    complete = search_router.search_documents(
        query="",
        mode="fulltext",
        quality="complete",
        page=1,
        page_size=24,
        db=db,
    )
    counts = search_router.get_quality_counts(db)
    db.close()

    assert [item.document.id for item in flagged.items] == [flagged_id]
    assert counts["single_char_tag"] == 1
    assert flagged_id not in [item.document.id for item in complete.items]
    assert clean_id in [item.document.id for item in complete.items]


def test_fix_quality_single_char_tag_delegates_matching_doc_ids_to_batch_analysis(db_session, monkeypatch):
    # Doc: docs/code-map.md — fix_quality routes analysis-related gaps through
    #       Gemini Batch Analysis using explicit doc_ids.
    # Rule: single-character-tag documents are treated as an analysis gap and
    #       delegated exactly like the existing no_tags / no_summary cases.
    flagged_id = _add_doc(db_session, filename="flagged.pdf", tags=["x", "passport"])
    _add_doc(db_session, filename="clean.pdf", tags=["passport"])

    run_batch = AsyncMock()
    monkeypatch.setattr(tasks_module, "run_batch_analysis_gemini", run_batch)
    monkeypatch.setattr(tasks_module, "_log", lambda *a, **k: None)
    monkeypatch.setattr(tasks_module, "_set_progress", lambda *a, **k: None)
    monkeypatch.setattr(tasks_module, "_finish", lambda *a, **k: None)

    asyncio.run(tasks_module._fix_quality(123, {"quality_filter": "single_char_tag"}))

    run_batch.assert_awaited_once()
    task_id, config = run_batch.await_args.args
    assert task_id == 123
    assert config["quality_filter"] == "single_char_tag"
    assert config["doc_ids"] == [flagged_id]
