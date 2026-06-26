"""Library/indexing admin endpoints: stats, sync, batch jobs, log."""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from ..database import get_db
from ..models import Document, IndexingLog
from ..schemas import IndexingStats, LogEntry, SyncResponse
from ..services.storage import scan_library_for_new_files, compute_file_hash, guess_mime, infer_document_date
from ..services.thumbnails import generate_thumbnail, cleanup_orphan_thumbnails
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

    from ..config import settings as app_settings
    return IndexingStats(
        total=total,
        indexed=indexed,
        analyzed=analyzed,
        embedded=embedded,
        pending=pending,
        errors=errors,
        unclassified=unclassified,
        api_cost_total=float(cost_row or 0),
        library_path=str(Path(app_settings.library_path).resolve()),
    )


# ── Sync (scan library for new files) ────────────────────────────────────────

@router.post("/sync", response_model=SyncResponse)
def sync_library(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Step 1 — remove docs whose files are gone or located inside .docintell
    # (.docintell contains thumbnails/DB/Chroma — never user documents; they got
    # added by a previous bug in scan_library_for_new_files)
    from ..services.storage import get_library_path
    docintell_dir = get_library_path() / ".docintell"

    removed = 0
    for doc in db.query(Document).filter(Document.is_deleted == False).all():
        fp = Path(doc.filepath)
        missing = not fp.exists()
        phantom = fp.is_relative_to(docintell_dir)
        if missing or phantom:
            # Delete the thumbnail file immediately so it doesn't linger
            if doc.thumbnail_path:
                try:
                    Path(doc.thumbnail_path).unlink(missing_ok=True)
                except OSError:
                    pass
            doc.is_deleted = True
            removed += 1
            reason = "phantom (.docintell)" if phantom else "file missing on disk"
            _log(db, step="sync", status="done",
                 message=f"Removed ({reason}): {doc.filename}",
                 document_id=doc.id, level="trace")
    if removed:
        db.commit()

    # Step 2 — discover new files on disk
    known = {d.filepath for d in db.query(Document.filepath).filter(Document.is_deleted == False)}
    new_paths = scan_library_for_new_files(known)

    added = 0
    new_ids: list[int] = []
    for p in new_paths:
        try:
            file_hash = compute_file_hash(p)
            if db.query(Document).filter(Document.file_hash == file_hash, Document.is_deleted == False).first():
                continue
            mime = guess_mime(p)
            doc = Document(
                filename=p.name,
                filepath=str(p),
                file_hash=file_hash,
                file_size=p.stat().st_size,
                mime_type=mime,
                document_date=infer_document_date(p),
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

    # Step 3 — backfill document_date for existing docs that still have none
    backfilled = 0
    for doc in db.query(Document).filter(
        Document.is_deleted == False,
        Document.document_date.is_(None),
    ).all():
        inferred = infer_document_date(Path(doc.filepath))
        if inferred:
            doc.document_date = inferred
            backfilled += 1
    if backfilled:
        db.commit()

    # Step 4 — queue OCR for every newly discovered document
    for doc_id in new_ids:
        background_tasks.add_task(index_document, doc_id)

    # Step 5 — remove thumbnail files that no active document references
    active_thumbs = {
        doc.thumbnail_path
        for doc in db.query(Document).filter(
            Document.is_deleted == False,
            Document.thumbnail_path.isnot(None),
        ).all()
        if doc.thumbnail_path
    }
    thumbs_cleaned = cleanup_orphan_thumbnails(active_thumbs)

    parts = [f"Found {len(new_paths)} new files, added {added}"]
    if removed:
        parts.append(f"removed {removed} missing")
    if backfilled:
        parts.append(f"backfilled dates for {backfilled}")
    if thumbs_cleaned:
        parts.append(f"cleaned {thumbs_cleaned} orphan thumbnail(s)")
    _log(db, step="sync", status="done", message=", ".join(parts), level="info")
    return SyncResponse(found=len(new_paths), new_files=added, removed=removed, message=", ".join(parts))


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

_LEVEL_RANK = {"trace": 5, "debug": 10, "info": 20, "warning": 30, "error": 40}


@router.get("/log", response_model=list[LogEntry])
def get_log(limit: int = 100, min_level: str = "info", db: Session = Depends(get_db)):
    rank = _LEVEL_RANK.get(min_level, 20)
    visible = [lvl for lvl, r in _LEVEL_RANK.items() if r >= rank]
    return (
        db.query(IndexingLog)
        .filter(IndexingLog.level.in_(visible))
        .order_by(IndexingLog.created_at.desc())
        .limit(limit)
        .all()
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(db: Session, step: str, status: str, message: str = "", document_id: int = None, level: str = "info"):
    entry = IndexingLog(step=step, status=status, message=message, document_id=document_id, level=level)
    db.add(entry)
    db.commit()
