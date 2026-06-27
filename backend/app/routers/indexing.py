"""
Indexing control endpoints — manual triggers for the OCR pipeline.

POST /api/indexing/document/{id}   run OCR on a single document
POST /api/indexing/batch           run OCR on all pending (up to limit)
POST /api/indexing/reclassify/{id} re-run AI Analysis only (Phase 3)
GET  /api/indexing/status          pending/running counts
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document
from ..services.indexer import index_document, index_pending_batch, reclassify_document

router = APIRouter(prefix="/api/indexing", tags=["indexing"])


@router.post("/document/{doc_id}")
async def trigger_single(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    background_tasks.add_task(index_document, doc_id, True)  # force_full=True
    return {"message": f"Indexing started for document {doc_id}"}


@router.post("/batch")
async def trigger_batch(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
):
    """Queue batch OCR for up to `limit` pending documents."""
    background_tasks.add_task(_run_batch, limit)
    return {"message": f"Batch indexing queued (limit={limit})"}


@router.post("/reclassify/{doc_id}")
async def trigger_reclassify(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    background_tasks.add_task(reclassify_document, doc_id)
    return {"message": f"Re-classification queued for document {doc_id}"}


@router.post("/suggest-type/{doc_id}")
async def suggest_type(doc_id: int, db: Session = Depends(get_db)):
    """Return top-3 LLM type suggestions for a document."""
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    existing = [
        r[0] for r in db.query(distinct(Document.document_type))
        .filter(
            Document.document_type.isnot(None),
            Document.document_type != "unclassified",
            Document.document_type != "other",
        )
        .all()
    ]

    from ..services.ai_analysis import suggest_document_types
    suggestions = await suggest_document_types(
        doc.summary or "",
        doc.ocr_text or "",
        existing,
        db,
    )
    return {"suggestions": suggestions, "existing_types": existing}


@router.get("/status")
def get_indexing_status(db: Session = Depends(get_db)):
    base = db.query(Document).filter(Document.is_deleted == False)
    pending_count = base.filter(Document.ocr_status == "pending").count()
    error_count   = base.filter(Document.ocr_status == "error").count()

    # Up to 5 sample filenames: errors first, then pending
    samples: list[dict] = []
    for doc in (
        base.filter(Document.ocr_status.in_(["error", "pending"]))
        .order_by(
            (Document.ocr_status == "error").desc(),
            Document.id.asc(),
        )
        .limit(5)
        .all()
    ):
        samples.append({"filename": doc.filename, "status": doc.ocr_status})

    return {
        "total":   base.count(),
        "pending": pending_count,
        "done":    base.filter(Document.ocr_status == "done").count(),
        "error":   error_count,
        "samples": samples,
    }


async def _run_batch(limit: int) -> None:
    result = await index_pending_batch(limit)
    import logging
    logging.getLogger(__name__).info("Batch complete: %s", result)
