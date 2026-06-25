"""
Indexing pipeline: OCR → Thumbnail → AI Vision → AI Analysis → Embedding.

Each step is independent and can be re-run.
Vision only runs when 'enable_ai_vision' = 'true' in AppSettings.
Embedding runs after analysis; falls back silently if chromadb/ST unavailable.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import AppSettings, Document, IndexingLog
from .ocr import extract_text
from .thumbnails import generate_thumbnail
from .ai_analysis import analyze_document
from .ai_vision import describe_document

log = logging.getLogger(__name__)


# ── Per-document pipeline ─────────────────────────────────────────────────────

async def index_document(document_id: int) -> None:
    """Full pipeline: OCR → Thumbnail → Vision → Analysis → Embedding."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return

        await _run_ocr(doc, db)
        _run_thumbnail(doc, db)
        await _run_vision(doc, db)
        await _run_analysis(doc, db)
        await _run_embedding(doc, db)
        doc.indexed_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        log.error("index_document(%s) crashed: %s", document_id, e)
    finally:
        db.close()


# ── Step 1 — OCR ──────────────────────────────────────────────────────────────

async def _run_ocr(doc: Document, db: Session) -> None:
    if doc.ocr_status == "done":
        return

    doc.ocr_status = "pending"
    db.commit()

    try:
        text = await extract_text(doc.filepath)
        doc.ocr_text = text
        doc.ocr_status = "done"
        _log(db, doc, "ocr", "done")
    except Exception as e:
        doc.ocr_status = "error"
        doc.ocr_error = str(e)
        _log(db, doc, "ocr", "error", str(e))
        log.warning("OCR failed for doc %s: %s", doc.id, e)

    db.commit()


# ── Step 2 — Thumbnail ────────────────────────────────────────────────────────

def _run_thumbnail(doc: Document, db: Session) -> None:
    if doc.thumbnail_path:
        return
    try:
        thumb = generate_thumbnail(doc.filepath, doc.id)
        if thumb:
            doc.thumbnail_path = thumb
            db.commit()
    except Exception as e:
        log.warning("Thumbnail failed for doc %s: %s", doc.id, e)


# ── Step 3 — AI Vision ────────────────────────────────────────────────────────

async def _run_vision(doc: Document, db: Session) -> None:
    if doc.vision_status == "done":
        return

    # Check AppSettings toggle (default: disabled)
    setting = db.query(AppSettings).filter(AppSettings.key == "enable_ai_vision").first()
    if not setting or setting.value != "true":
        doc.vision_status = "skipped"
        db.commit()
        return

    doc.vision_status = "pending"
    db.commit()

    try:
        result = await describe_document(doc.filepath, db)
        if result is None:
            doc.vision_status = "skipped"
            _log(db, doc, "vision", "skipped", "No vision provider configured")
        else:
            text, cost = result
            doc.vision_description = text
            doc.api_cost_vision = cost
            doc.vision_status = "done"
            _log(db, doc, "vision", "done")
    except Exception as e:
        doc.vision_status = "error"
        doc.vision_error = str(e)
        _log(db, doc, "vision", "error", str(e))
        log.warning("Vision failed for doc %s: %s", doc.id, e)

    db.commit()


# ── Step 4 — AI Analysis ──────────────────────────────────────────────────────

async def _run_analysis(doc: Document, db: Session) -> None:
    if doc.analysis_status == "done":
        return
    if not doc.ocr_text and not doc.vision_description:
        doc.analysis_status = "skipped"
        db.commit()
        return

    doc.analysis_status = "pending"
    db.commit()

    try:
        result = await analyze_document(
            doc.ocr_text or "",
            db,
            vision_description=doc.vision_description,
        )
        if result is None:
            doc.analysis_status = "skipped"
            _log(db, doc, "analysis", "skipped", "No AI provider configured")
        else:
            doc.summary            = result.summary
            doc.document_type      = result.document_type
            doc.tags               = result.tags
            doc.language           = result.language
            doc.organization       = result.organization
            doc.amount             = result.amount
            doc.amount_currency    = result.amount_currency
            doc.person_first_name  = result.person_first_name
            doc.person_last_name   = result.person_last_name
            if result.document_date:
                try:
                    doc.document_date = datetime.strptime(result.document_date, "%Y-%m-%d")
                except ValueError:
                    pass
            doc.api_cost_analysis  = result.cost_usd
            doc.analysis_status    = "done"
            _log(db, doc, "analysis", "done",
                 f"Type: {result.document_type}, lang: {result.language}")
    except Exception as e:
        doc.analysis_status = "error"
        doc.analysis_error  = str(e)
        _log(db, doc, "analysis", "error", str(e))
        log.warning("Analysis failed for doc %s: %s", doc.id, e)

    db.commit()


# ── Step 5 — Embedding ────────────────────────────────────────────────────────

async def _run_embedding(doc: Document, db: Session) -> None:
    """Add/update document embedding in ChromaDB. Skips silently on error."""
    text = " ".join(filter(None, [
        doc.summary or "",
        (doc.ocr_text or "")[:1500],
    ])).strip()
    if not text:
        return
    try:
        from .embeddings import embed_document
        await asyncio.to_thread(embed_document, doc.id, text)
    except Exception as e:
        log.warning("Embedding failed for doc %s: %s", doc.id, e)


# ── Batch processing ──────────────────────────────────────────────────────────

async def index_pending_batch(limit: int = 50) -> dict:
    """Process up to `limit` documents whose ocr_status is 'pending'."""
    db = SessionLocal()
    try:
        pending = (
            db.query(Document)
            .filter(Document.is_deleted == False, Document.ocr_status == "pending")
            .limit(limit)
            .all()
        )
        processed = errors = 0
        for doc in pending:
            try:
                await _run_ocr(doc, db)
                _run_thumbnail(doc, db)
                await _run_vision(doc, db)
                await _run_analysis(doc, db)
                await _run_embedding(doc, db)
                doc.indexed_at = datetime.utcnow()
                db.commit()
                processed += 1
            except Exception as e:
                errors += 1
                log.error("Batch: doc %s failed: %s", doc.id, e)

        return {"processed": processed, "errors": errors, "total_pending": len(pending)}
    finally:
        db.close()


async def reclassify_pending_batch(limit: int = 100) -> dict:
    """Re-run AI Analysis + Embedding on OCR-done docs not yet analyzed."""
    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                Document.is_deleted == False,
                Document.ocr_status == "done",
                Document.analysis_status != "done",
            )
            .limit(limit)
            .all()
        )
        processed = errors = 0
        for doc in docs:
            try:
                doc.analysis_status = "pending"
                db.commit()
                await _run_analysis(doc, db)
                await _run_embedding(doc, db)
                processed += 1
            except Exception as e:
                errors += 1
                log.error("Reclassify batch: doc %s failed: %s", doc.id, e)

        return {"processed": processed, "errors": errors}
    finally:
        db.close()


# ── Re-classify single document ───────────────────────────────────────────────

async def reclassify_document(document_id: int) -> None:
    """Re-run AI Analysis (and re-embed) on an already-OCR'd document."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return
        if not doc.ocr_text and not doc.vision_description:
            _log(db, doc, "analysis", "skipped", "No OCR text — run OCR first")
            db.commit()
            return
        doc.analysis_status = "pending"
        db.commit()
        await _run_analysis(doc, db)
        await _run_embedding(doc, db)
    except Exception as e:
        log.error("reclassify_document(%s) crashed: %s", document_id, e)
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(db: Session, doc: Document, step: str, status: str, message: str = "") -> None:
    entry = IndexingLog(
        document_id=doc.id,
        filename=doc.filename,
        step=step,
        status=status,
        message=message,
    )
    db.add(entry)
    db.commit()
