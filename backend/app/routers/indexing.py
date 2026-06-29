"""
Indexing control endpoints — manual triggers for the OCR pipeline.

POST /api/indexing/document/{id}   run OCR on a single document
POST /api/indexing/batch           run OCR on all pending (up to limit)
POST /api/indexing/reclassify/{id} re-run AI Analysis only (Phase 3)
GET  /api/indexing/status          pending/running counts
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import distinct, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document
from ..services.indexer import (
    index_document, index_pending_batch, reclassify_document, embed_document_by_id,
)

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
    from ..models import AppSettings
    base = db.query(Document).filter(Document.is_deleted == False)
    pending_count = base.filter(Document.ocr_status == "pending").count()
    error_count   = base.filter(Document.ocr_status == "error").count()

    mode_row = db.query(AppSettings).filter(AppSettings.key == "auto_process_mode").first()
    mode = mode_row.value if mode_row else "full"

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
        "mode":    mode,
    }


async def _run_batch(limit: int) -> None:
    result = await index_pending_batch(limit)
    import logging
    logging.getLogger(__name__).info("Batch complete: %s", result)


class _DispatchQualityRequest(BaseModel):
    quality: str


@router.post("/dispatch-quality")
async def dispatch_quality(
    body: _DispatchQualityRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start background processing for all documents with the given quality gap.

    quality values:
      no_ocr       → re-run full OCR + analysis pipeline
      no_embedding → embed without re-running analysis
      no_analysis  → re-run analysis (reclassify)
      no_summary   → re-run analysis
      no_tags      → re-run analysis
      no_category  → re-run analysis
    """
    from sqlalchemy import String
    q = body.quality
    base = db.query(Document).filter(Document.is_deleted == False)

    if q == "no_ocr":
        docs = base.filter(
            or_(
                Document.ocr_status != "done",
                Document.ocr_text == None,
                Document.ocr_text == "",
            )
        ).all()
        for doc in docs:
            background_tasks.add_task(index_document, doc.id, True)
        return {"dispatched": len(docs), "operation": "ocr"}

    if q == "no_embedding":
        try:
            from ..services.embeddings import embedded_ids as get_embedded_ids
            emb_ids = get_embedded_ids()
            docs = base.filter(~Document.id.in_(emb_ids)).all()
        except Exception:
            docs = []
        for doc in docs:
            background_tasks.add_task(embed_document_by_id, doc.id)
        return {"dispatched": len(docs), "operation": "embedding"}

    if q == "no_analysis":
        docs = base.filter(Document.analysis_status != "done").all()
    elif q == "no_summary":
        docs = base.filter(or_(Document.summary == None, Document.summary == "")).all()
    elif q == "no_tags":
        docs = base.filter(
            or_(Document.tags == None, Document.tags.cast(String) == "[]")
        ).all()
    elif q == "no_category":
        docs = base.filter(
            or_(
                Document.document_type == None,
                Document.document_type == "unclassified",
                Document.document_type == "other",
            )
        ).all()
    else:
        raise HTTPException(400, f"Unknown quality filter: {q!r}")

    for doc in docs:
        background_tasks.add_task(reclassify_document, doc.id)
    return {"dispatched": len(docs), "operation": "reclassify"}
