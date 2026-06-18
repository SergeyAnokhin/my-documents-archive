"""Background indexing worker.

Processes documents through OCR, AI Vision, and AI Analysis steps.
Phases: 2 (OCR), 3 (AI Analysis), 4 (AI Vision).
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import get_ai_config
from backend.database import SessionLocal
from backend.models import Document, IndexingStatus
from backend.ocr import process_document
from backend.ai_analysis import analyze_document

logger = logging.getLogger(__name__)


def index_document(doc_id: str):
    """Run full indexing pipeline on a single document."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            logger.warning("Document %s not found", doc_id)
            return

        file_path = Path(doc.file_path)
        if not file_path.exists():
            doc.ocr_status = IndexingStatus.error
            db.commit()
            return

        ai_config = get_ai_config()
        changed = False

        # ── Step 1: OCR ───────────────────────────────────
        if doc.ocr_status == IndexingStatus.pending:
            ocr_text = process_document(file_path)
            doc.ocr_text = ocr_text or ""
            doc.ocr_status = IndexingStatus.done
            changed = True

        # ── Step 3: AI Analysis ───────────────────────────
        if ai_config.get("analysis_enabled", True) and doc.analysis_status == IndexingStatus.pending:
            if doc.ocr_text and doc.ocr_text.strip():
                try:
                    result = analyze_document(doc.ocr_text, doc.original_filename)
                    doc.summary = result.get("summary", "")
                    doc.tags = result.get("tags", [])
                    doc.doc_type = result.get("doc_type", "")
                    doc.doc_language = result.get("language", "")
                    if result.get("doc_date"):
                        from datetime import datetime
                        try:
                            doc.doc_date = datetime.strptime(result["doc_date"], "%Y-%m-%d")
                        except (ValueError, TypeError):
                            pass
                    doc.analysis_status = IndexingStatus.done
                    changed = True
                except Exception as e:
                    logger.warning("AI analysis failed for %s: %s", doc_id, e)
                    doc.analysis_status = IndexingStatus.error
                    changed = True
            else:
                # No OCR text — mark as skipped (will retry after Vision)
                doc.analysis_status = IndexingStatus.skipped
                changed = True

        if changed:
            db.commit()

        # Future: Step 2 (AI Vision) — Phase 4

    except Exception as e:
        logger.error("Indexing failed for %s: %s", doc_id, e)
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                if doc.ocr_status == IndexingStatus.pending:
                    doc.ocr_status = IndexingStatus.error
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def index_next_batch(limit: int = 10):
    """Process the next N pending documents (OCR then AI Analysis)."""
    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                (Document.ocr_status == IndexingStatus.pending)
                | (Document.analysis_status == IndexingStatus.pending)
            )
            .limit(limit)
            .all()
        )
        for doc in docs:
            index_document(doc.id)
        return len(docs)
    finally:
        db.close()
