"""Background indexing worker.

Processes documents through OCR, AI Vision, and AI Analysis steps.
Currently implements Phase 2: OCR only.
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import SUPPORTED_FORMATS
from backend.database import SessionLocal
from backend.models import Document, IndexingStatus
from backend.ocr import process_document

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

        # Step 1: OCR
        if doc.ocr_status == IndexingStatus.pending:
            doc.ocr_status = IndexingStatus.done  # optimistic
            ocr_text = process_document(file_path)
            if ocr_text:
                doc.ocr_text = ocr_text
            else:
                doc.ocr_text = ""
                # Still mark done — empty text is valid for unreadable docs
            db.commit()

        # Future: Step 2 (AI Vision), Step 3 (AI Analysis)
        # These go here when phases 3–4 are implemented

    except Exception as e:
        logger.error("Indexing failed for %s: %s", doc_id, e)
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.ocr_status = IndexingStatus.error
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def index_next_batch(limit: int = 10):
    """Process the next N pending documents."""
    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(Document.ocr_status == IndexingStatus.pending)
            .limit(limit)
            .all()
        )
        for doc in docs:
            index_document(doc.id)
        return len(docs)
    finally:
        db.close()
