"""Library/indexing admin endpoints: stats, sync, batch jobs, log."""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from ..database import get_db
from ..models import Document, IndexingLog
from ..schemas import IndexingStats, LogEntry, SyncResponse
from ..services.storage import scan_library_for_new_files, compute_file_hash, guess_mime
from ..services.thumbnails import generate_thumbnail
from ..services.indexer import (
    index_document,
    index_pending_batch,
    reclassify_pending_batch,
    reclassify_unclassified_batch,
)

router = APIRouter()


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=IndexingStats)
def get_stats(db: Session = Depends(get_db)):
    base = db.query(Document).filter(Document.is_deleted == False)
    total    = base.count()
    indexed  = base.filter(Document.ocr_status == "done").count()
    analyzed = base.filter(Document.analysis_status == "done").count()
    pending  = base.filter(Document.ocr_status == "pending").count()
    errors   = base.filter(Document.ocr_status == "error").count()

    unclassified = base.filter(
        Document.analysis_status == "done",
        or_(
            Document.document_type == "unclassified",
            Document.document_type == "other",
            Document.document_type.is_(None),
        ),
    ).count()

    cost_row = db.query(
        func.coalesce(func.sum(Document.api_cost_vision), 0) +
        func.coalesce(func.sum(Document.api_cost_analysis), 0)
    ).filter(Document.is_deleted == False).scalar()

    try:
        from ..services.embeddings import collection_count
        embedded = collection_count()
    except Exception:
        embedded = 0

    return IndexingStats(
        total=total,
        indexed=indexed,
        analyzed=analyzed,
        embedded=embedded,
        pending=pending,
        errors=errors,
        unclassified=unclassified,
        api_cost_total=float(cost_row or 0),
    )


# ── Sync (scan library for new files) ────────────────────────────────────────

@router.post("/sync", response_model=SyncResponse)
def sync_library(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    known = {d.filepath for d in db.query(Document.filepath).filter(Document.is_deleted == False)}
    new_paths = scan_library_for_new_files(known)

    added = 0
    new_ids: list[int] = []
    for p in new_paths:
        try:
            file_hash = compute_file_hash(p)
            if db.query(Document).filter(Document.file_hash == file_hash).first():
                continue
            mime = guess_mime(p)
            doc = Document(
                filename=p.name,
                filepath=str(p),
                file_hash=file_hash,
                file_size=p.stat().st_size,
                mime_type=mime,
            )
            db.add(doc)
            db.flush()
            thumb = generate_thumbnail(str(p), doc.id)
            if thumb:
                doc.thumbnail_path = thumb
            new_ids.append(doc.id)
            added += 1
        except Exception:
            pass

    db.commit()

    # Queue OCR for every newly discovered document
    for doc_id in new_ids:
        background_tasks.add_task(index_document, doc_id)

    _log(db, step="sync", status="done", message=f"Found {len(new_paths)} new files, added {added}")
    return SyncResponse(found=len(new_paths), new_files=added, message=f"Added {added} new documents")


# ── Batch indexing ───────────────────────────────────────────────────────────

@router.post("/batch-index")
async def batch_index(background_tasks: BackgroundTasks, limit: int = 50):
    """Queue OCR + analysis for up to `limit` pending documents."""
    background_tasks.add_task(_run_batch_bg, limit)
    return {"message": f"Batch indexing queued (up to {limit} documents)"}


async def _run_batch_bg(limit: int) -> None:
    result = await index_pending_batch(limit)
    import logging
    logging.getLogger(__name__).info("Admin batch complete: %s", result)


@router.post("/reclassify-all")
async def reclassify_all(background_tasks: BackgroundTasks, limit: int = 200):
    """Re-run AI Analysis on all OCR-done documents not yet analyzed."""
    background_tasks.add_task(_run_reclassify_bg, limit)
    return {"message": f"Re-classification queued (up to {limit} documents)"}


async def _run_reclassify_bg(limit: int) -> None:
    result = await reclassify_pending_batch(limit)
    import logging
    logging.getLogger(__name__).info("Admin reclassify complete: %s", result)


@router.post("/reclassify-unclassified")
async def reclassify_unclassified(background_tasks: BackgroundTasks, limit: int = 200):
    """Re-run AI Analysis on all unclassified/other docs not manually set."""
    background_tasks.add_task(_run_reclassify_unclassified_bg, limit)
    return {"message": f"Unclassified re-classification queued (up to {limit} documents)"}


async def _run_reclassify_unclassified_bg(limit: int) -> None:
    result = await reclassify_unclassified_batch(limit)
    import logging
    logging.getLogger(__name__).info("Admin reclassify-unclassified complete: %s", result)


# ── Log ───────────────────────────────────────────────────────────────────────

@router.get("/log", response_model=list[LogEntry])
def get_log(limit: int = 100, db: Session = Depends(get_db)):
    return (
        db.query(IndexingLog)
        .order_by(IndexingLog.created_at.desc())
        .limit(limit)
        .all()
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(db: Session, step: str, status: str, message: str = "", document_id: int = None):
    entry = IndexingLog(step=step, status=status, message=message, document_id=document_id)
    db.add(entry)
    db.commit()
