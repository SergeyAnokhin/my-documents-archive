"""Pins how analysis metadata is written onto a Document — see docs/code-map.md (indexer.py).

`_apply_analysis_result` is the single helper shared by Step 3 (vision-as-analysis)
and Step 4 (text analysis); both call it so the two paths populate identical columns.

`_is_docx`/`_run_docx_extract` are the native-text branch used for .docx files:
no OCR/Vision/Thumbnail step ever runs for them (see docs/code-map.md — Key Data
Flow). `_run_docx_extract` commits, so it's driven against a real in-memory
SQLite DB rather than db=None (matches the harness used in test_batch_ocr.py).
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AppSettings, Document
from app.services.ai_analysis import AnalysisResult
from app.services.indexer import (
    _apply_analysis_result,
    _is_docx,
    _is_unclassified,
    _run_docx_extract,
    _run_vision,
)


def test_apply_analysis_result_writes_all_metadata_columns():
    # Rule: every AnalysisResult content field lands on the matching Document column,
    # source is marked "auto", and a valid YYYY-MM-DD date is parsed to a datetime.
    doc = Document(filename="x.pdf", filepath="/x.pdf", source="sync")
    result = AnalysisResult(
        summary="a summary",
        title="A Short Title",
        document_type="invoice",
        document_type_confidence=0.9,
        tags=["a", "b"],
        language="en",
        organization="ACME",
        amount=150.5,
        amount_currency="EUR",
        person_first_name="John",
        person_last_name="Doe",
        document_date="2024-03-15",
    )
    _apply_analysis_result(doc, result, db=None)

    assert doc.document_type == "invoice"
    assert doc.classification_confidence == 0.9
    assert doc.classification_source == "auto"
    assert doc.tags == ["a", "b"]
    assert doc.organization == "ACME"
    assert doc.amount == 150.5
    assert doc.document_date == datetime(2024, 3, 15)
    assert doc.title == "A Short Title"


def test_apply_analysis_result_empty_title_stored_as_none():
    # Rule: an empty/absent title normalises to None on the Document column,
    # so the frontend's `doc.title || doc.filename` fallback kicks in cleanly.
    doc = Document(filename="x.pdf", filepath="/x.pdf", source="sync")
    _apply_analysis_result(doc, AnalysisResult(document_type="letter"), db=None)
    assert doc.title is None


def test_apply_analysis_result_ignores_invalid_date():
    # Rule: a malformed document_date is silently dropped (column stays unset),
    # never raises — a bad LLM date must not break indexing.
    doc = Document(filename="x.pdf", filepath="/x.pdf", source="sync")
    result = AnalysisResult(document_type="letter", document_date="not-a-date")
    _apply_analysis_result(doc, result, db=None)

    assert doc.document_type == "letter"
    assert doc.document_date is None


def test_is_unclassified_predicate():
    # Rule: _is_unclassified returns True only for None / "unclassified" / "other" —
    # these are the three values the batch reclassify jobs target.
    assert _is_unclassified(Document(filename="a", filepath="/a", document_type=None))
    assert _is_unclassified(Document(filename="a", filepath="/a", document_type="unclassified"))
    assert _is_unclassified(Document(filename="a", filepath="/a", document_type="other"))
    assert not _is_unclassified(Document(filename="a", filepath="/a", document_type="invoice"))


# ── .docx native-text branch ─────────────────────────────────────────────────

def test_is_docx_checks_extension():
    # Rule: only a .docx extension (case-insensitive) routes to the native-
    # extraction branch — everything else (including no extension) does not.
    assert _is_docx(Document(filename="a.docx", filepath="/lib/a.docx"))
    assert _is_docx(Document(filename="a.DOCX", filepath="/lib/a.DOCX"))
    assert not _is_docx(Document(filename="a.pdf", filepath="/lib/a.pdf"))
    assert not _is_docx(Document(filename="a", filepath="/lib/a"))


def _make_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_run_docx_extract_sets_native_marker_and_done_status(tmp_path):
    # Rule: a successful native extraction sets ocr_status=done, ocr_model=
    # "native" (so the frontend never mistakes it for AI-OCR — see
    # DocumentCard.tsx isAiOcr()), and vision_status=skipped (no page image
    # exists for docx, so Vision is architecturally unreachable).
    db = _make_session(tmp_path)
    doc = Document(filename="a.docx", filepath=str(tmp_path / "a.docx"), source="sync")
    db.add(doc)
    db.commit()

    with patch("app.services.docx_extract.extract_docx_text", return_value="extracted text"):
        asyncio.run(_run_docx_extract(doc, db))

    assert doc.ocr_status == "done"
    assert doc.ocr_model == "native"
    assert doc.ocr_text == "extracted text"
    assert doc.vision_status == "skipped"


def test_run_docx_extract_marks_error_on_failure(tmp_path):
    # Rule: an extraction failure (corrupt/encrypted file) sets ocr_status=
    # error and records the exception message, mirroring services/ocr.py's
    # extract_text() failure contract — it never raises out of the pipeline.
    db = _make_session(tmp_path)
    doc = Document(filename="a.docx", filepath=str(tmp_path / "a.docx"), source="sync")
    db.add(doc)
    db.commit()

    with patch("app.services.docx_extract.extract_docx_text", side_effect=ValueError("corrupt file")):
        asyncio.run(_run_docx_extract(doc, db))

    assert doc.ocr_status == "error"
    assert doc.ocr_error == "corrupt file"


# ── Step 3 — Vision vs. fuller OCR/native text ───────────────────────────────

def _enable_vision(db):
    db.add(AppSettings(key="enable_ai_vision", value="true"))
    db.commit()


def test_run_vision_applies_analysis_when_no_fuller_text_exists(tmp_path):
    # Rule: when the document has no other real text (scan with no OCR text,
    # or OCR text below the threshold), the capable model's combined
    # vision+analysis JSON is trusted directly and Step 4 is skipped.
    db = _make_session(tmp_path)
    _enable_vision(db)
    doc = Document(filename="a.pdf", filepath=str(tmp_path / "a.pdf"), source="sync", ocr_text="")
    db.add(doc)
    db.commit()

    analysis = AnalysisResult(summary="s", title="T", document_type="invoice")
    with patch("app.services.indexer.describe_document", AsyncMock(return_value=("page 1 text", analysis, 0.01))):
        asyncio.run(_run_vision(doc, db))

    assert doc.document_type == "invoice"
    assert doc.analysis_status == "done"


def test_run_vision_defers_to_step4_when_fuller_ocr_text_exists(tmp_path):
    # Rule: when a fuller OCR/native text already exists (multi-page document,
    # first page is just a cover/title), vision's page-1-only analysis must
    # NOT overwrite it — Step 4 is left to run on the full text instead.
    db = _make_session(tmp_path)
    _enable_vision(db)
    full_text = "Article 1. " * 40  # well above the override threshold
    doc = Document(filename="a.pdf", filepath=str(tmp_path / "a.pdf"), source="sync", ocr_text=full_text)
    db.add(doc)
    db.commit()

    analysis = AnalysisResult(summary="cover page only", title="Title Page", document_type="unclassified")
    with patch("app.services.indexer.describe_document", AsyncMock(return_value=("Title Page", analysis, 0.01))):
        asyncio.run(_run_vision(doc, db))

    assert doc.document_type is None  # untouched — Step 4 will set it from full_text
    assert doc.analysis_status != "done"
    assert doc.vision_description == "Title Page"  # transcription is still recorded
