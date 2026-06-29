"""Tasks API — create, run, stop, and inspect background processing jobs."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import Document, Task, TaskLog
from ..schemas import TaskCreate, TaskLogOut, TaskOut, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[TaskOut])
def list_tasks(db: Session = Depends(get_db)):
    return db.query(Task).order_by(Task.sort_order.asc(), Task.id.asc()).all()


@router.post("", response_model=TaskOut)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    sort_order = body.sort_order if body.sort_order else db.query(Task).count()
    task = Task(
        task_type=body.task_type,
        title=body.title,
        config=body.config,
        sort_order=sort_order,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if body.title is not None:
        task.title = body.title
    if body.config is not None:
        task.config = body.config
    if body.sort_order is not None:
        task.sort_order = body.sort_order
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    db.query(TaskLog).filter(TaskLog.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    return {"ok": True}


# ── Candidate counts (pre-flight info for the create form) ───────────────────

@router.get("/candidates")
def get_candidate_counts(db: Session = Depends(get_db)):
    """Return how many documents each task type would process right now (scope=1 for OCR tasks)."""
    from sqlalchemy import or_
    from ..services.batch_ocr import _scope_filter

    base = db.query(Document).filter(Document.is_deleted == False)

    pending = base.filter(Document.ocr_status == "pending").count()

    reclassify_all_count = base.filter(
        Document.ocr_status == "done",
    ).count()

    reclassify_unclassified_count = base.filter(
        Document.ocr_status == "done",
        Document.manually_classified != True,
        or_(
            Document.document_type == "unclassified",
            Document.document_type == "other",
            Document.document_type.is_(None),
        ),
    ).count()

    batch_analysis_count = base.filter(
        Document.ocr_text.isnot(None),
        Document.ocr_text != "",
        Document.analysis_status != "done",
    ).count()

    batch_ocr_scope1 = _scope_filter(db.query(Document), 1).count()

    recluster_count = base.filter(
        Document.ocr_status == "done",
        Document.analysis_status == "done",
        Document.summary.isnot(None),
        Document.summary != "",
    ).count()

    # Docs that can be embedded (have summary OR ocr_text) but aren't in ChromaDB yet.
    # Must match the same criterion as _run_embedding in services/indexer.py.
    try:
        from sqlalchemy import and_
        from ..services.embeddings import embedded_ids
        embeddable_ids = {
            r[0] for r in base.filter(
                or_(
                    and_(Document.summary.isnot(None), Document.summary != ""),
                    and_(Document.ocr_text.isnot(None), Document.ocr_text != ""),
                )
            ).with_entities(Document.id).all()
        }
        embed_missing_count = len(embeddable_ids - embedded_ids())
    except Exception:
        embed_missing_count = None

    return {
        "index_unindexed": pending,
        "sync_library": None,
        "reclassify_unclassified": reclassify_unclassified_count,
        "reclassify_all": reclassify_all_count,
        "recluster": recluster_count,
        "embed_missing": embed_missing_count,
        "fix_quality": None,
        "batch_ocr_mistral": batch_ocr_scope1,
        "batch_ocr_gemini": batch_ocr_scope1,
        "batch_analysis_gemini": batch_analysis_count,
        "cleanup_missing": None,
        "compress_images": None,
    }


@router.get("/candidates/compress")
def get_compress_count(threshold: int = 1024):
    """Return how many image files have long side > threshold pixels."""
    from ..services.image_compress import count_compress_candidates
    over, total = count_compress_candidates(threshold)
    return {"count": over, "total_images": total}


@router.get("/candidates/scope")
def get_scope_count(
    task_type: str,
    scope: int = 1,
    db: Session = Depends(get_db),
):
    """Return how many documents qualify for OCR batch tasks at a given cumulative scope level."""
    from ..services.batch_ocr import _scope_filter

    if task_type not in ("batch_ocr_mistral", "batch_ocr_gemini"):
        raise HTTPException(400, "scope count only applies to batch_ocr_mistral / batch_ocr_gemini")

    count = _scope_filter(db.query(Document), scope).count()
    return {"count": count}


# ── Control ───────────────────────────────────────────────────────────────────

@router.post("/stop-all")
def stop_all_tasks(db: Session = Depends(get_db)):
    db.query(Task).filter(Task.status == "running").update({"status": "stopped"})
    db.commit()
    return {"message": "All tasks stopped"}


@router.post("/{task_id}/run")
async def run_task(task_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == "running":
        return {"message": "Task already running"}

    task.status = "running"
    task.started_at = datetime.utcnow()
    task.finished_at = None
    task.progress_current = 0
    task.progress_total = 0
    db.commit()

    background_tasks.add_task(_run_task_bg, task_id, task.task_type, task.config or {})
    return {"message": "Task started"}


@router.post("/{task_id}/stop")
def stop_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "stopped"
    db.commit()
    return {"message": "Task stopped"}


@router.post("/{task_id}/resume-batch")
async def resume_batch_task(task_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Resume polling for a remote batch job that kept running while the server was down."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == "running":
        return {"message": "Task already running"}
    if task.task_type not in (
        "batch_ocr_mistral", "batch_ocr_gemini", "batch_analysis_gemini",
        "reclassify_unclassified", "reclassify_all",
    ):
        raise HTTPException(400, "Only batch tasks support resume")

    batch_job_id = (task.result_summary or {}).get("batch_job_id")
    if not batch_job_id:
        raise HTTPException(400, "No remote batch_job_id found — task has no running remote job")

    task.status = "running"
    task.started_at = datetime.utcnow()
    task.finished_at = None
    db.commit()

    config = {**(task.config or {}), "resume_batch_job_id": str(batch_job_id)}
    background_tasks.add_task(_run_task_bg, task_id, task.task_type, config)
    return {"message": "Batch resume started"}


@router.get("/{task_id}/batch-result")
def download_batch_result(task_id: int, db: Session = Depends(get_db)):
    """Download the raw JSONL batch result file saved during processing."""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from ..config import settings

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    result_path = settings.docintell_dir / "batch_results" / f"task_{task_id}.jsonl"
    if not result_path.exists():
        raise HTTPException(404, "No batch result file found for this task")

    return FileResponse(
        str(result_path),
        media_type="application/octet-stream",
        filename=f"batch_result_task_{task_id}.jsonl",
    )


@router.get("/{task_id}/logs", response_model=List[TaskLogOut])
def get_task_logs(task_id: int, limit: int = 200, db: Session = Depends(get_db)):
    # Fetch the last `limit` rows (most recent), then return in chronological order.
    rows = (
        db.query(TaskLog)
        .filter(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


# ── Background runners ────────────────────────────────────────────────────────
# Shared runtime helpers live in services/task_runtime.py; batch OCR runners in
# services/batch_ocr.py. Imported under the local names the runners below use.
from ..services.task_runtime import (  # noqa: E402
    finish as _finish,
    is_stopped as _is_stopped,
    log_task as _log,
    set_progress as _set_progress,
)
from ..services.batch_ocr import run_batch_ocr_gemini, run_batch_ocr_mistral  # noqa: E402
from ..services.batch_analysis import run_batch_analysis_gemini  # noqa: E402
from ..services.image_compress import run_compress_images  # noqa: E402


async def _run_task_bg(task_id: int, task_type: str, config: dict) -> None:
    import logging
    logger = logging.getLogger(__name__)
    try:
        if task_type == "index_unindexed":
            await _index_unindexed(task_id, config)
        elif task_type == "sync_library":
            await _sync_library(task_id, config)
        elif task_type == "reclassify_unclassified":
            await _reclassify_unclassified(task_id, config)
        elif task_type == "reclassify_all":
            await _reclassify_all(task_id, config)
        elif task_type == "recluster":
            await _recluster(task_id, config)
        elif task_type == "embed_missing":
            await _embed_missing(task_id, config)
        elif task_type == "fix_quality":
            await _fix_quality(task_id, config)
        elif task_type == "batch_ocr_mistral":
            await run_batch_ocr_mistral(task_id, config)
        elif task_type == "batch_ocr_gemini":
            await run_batch_ocr_gemini(task_id, config)
        elif task_type == "batch_analysis_gemini":
            await run_batch_analysis_gemini(task_id, config)
        elif task_type == "cleanup_missing":
            await _cleanup_missing(task_id, config)
        elif task_type == "compress_images":
            await run_compress_images(task_id, config)
        else:
            _log(task_id, f"Unknown task type: {task_type}", "error")
            _finish(task_id, "error")
    except Exception as exc:
        logger.exception("Task %s (%s) failed", task_id, task_type)
        _log(task_id, f"Error: {exc}", "error")
        _finish(task_id, "error")


async def _index_unindexed(task_id: int, config: dict) -> None:
    from ..services.indexer import index_document

    limit = int(config.get("limit", 50))
    _log(task_id, f"Starting: index up to {limit} unindexed documents")

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(Document.ocr_status == "pending", Document.is_deleted == False)
            .limit(limit)
            .all()
        )
        total = len(docs)
        _log(task_id, f"Found {total} pending document(s)")
        _set_progress(task_id, 0, total)

        for i, doc in enumerate(docs):
            if _is_stopped(task_id):
                _log(task_id, f"Stopped after {i} document(s)")
                return
            try:
                await index_document(doc.id)
                db.refresh(doc)
                doc_type = doc.document_type or "unclassified"
                tags_str = ", ".join((doc.tags or [])[:5])
                suffix = f" [{tags_str}]" if tags_str else ""
                _log(task_id, f"✓ {doc.filename} → {doc_type}{suffix}")
            except Exception as exc:
                _log(task_id, f"✗ {doc.filename}: {exc}", "error")
            _set_progress(task_id, i + 1, total)
    finally:
        db.close()

    _finish(task_id, "done", {"processed": total})
    _log(task_id, f"Done — {total} document(s) processed")


async def _sync_library(task_id: int, config: dict) -> None:
    from ..services.indexer import index_document
    from ..services.storage import compute_file_hash, guess_mime, scan_library_for_new_files
    from ..services.thumbnails import generate_thumbnail

    _log(task_id, "Scanning library for new files…")

    db = SessionLocal()
    try:
        known = {
            d.filepath
            for d in db.query(Document.filepath).filter(Document.is_deleted == False)
        }
        new_paths = scan_library_for_new_files(known)
        _log(task_id, f"Found {len(new_paths)} new file(s)")
        _set_progress(task_id, 0, len(new_paths))

        added = 0
        for i, p in enumerate(new_paths):
            if _is_stopped(task_id):
                _log(task_id, f"Stopped — added {added} file(s)")
                return
            try:
                file_hash = compute_file_hash(p)
                if db.query(Document).filter(Document.file_hash == file_hash).first():
                    continue
                mime = guess_mime(p)
                doc = Document(
                    filename=p.name, filepath=str(p),
                    file_hash=file_hash, file_size=p.stat().st_size, mime_type=mime,
                )
                db.add(doc)
                db.flush()
                thumb = generate_thumbnail(str(p), doc.id)
                if thumb:
                    doc.thumbnail_path = thumb
                db.commit()
                await index_document(doc.id)
                added += 1
                _log(task_id, f"✓ Added: {p.name}")
            except Exception as exc:
                _log(task_id, f"✗ {p.name}: {exc}", "error")
            _set_progress(task_id, i + 1, len(new_paths))
    finally:
        db.close()

    _finish(task_id, "done", {"found": len(new_paths), "added": added})
    _log(task_id, f"Done — {added} new document(s) added")


async def _reclassify_unclassified(task_id: int, config: dict) -> None:
    await run_batch_analysis_gemini(task_id, {**config, "doc_scope": "unclassified"})


async def _reclassify_all(task_id: int, config: dict) -> None:
    await run_batch_analysis_gemini(task_id, {**config, "doc_scope": "pending"})


async def _recluster(task_id: int, config: dict) -> None:
    from ..services.recluster import run_recluster

    _log(task_id, "Starting: cluster-based recategorization of all analyzed documents")
    result = await run_recluster(task_id=task_id)
    _finish(task_id, "done", result)
    _log(task_id, f"Done — {result.get('applied', 0)} documents in {result.get('clusters', 0)} clusters")


async def _embed_missing(task_id: int, config: dict) -> None:
    """Embed every analyzed document (summary present) that has no embedding yet.

    Scans the whole archive — not just freshly-added docs — so it backfills the
    vector index after it was reset or for documents analyzed before embeddings
    existed. Logs the candidate count up front.

    config.force=True re-embeds ALL analyzed documents, ignoring existing vectors.
    """
    from ..services.indexer import _run_embedding
    from ..services.embeddings import embedded_ids

    force = bool(config.get("force", False))
    _log(task_id, "Starting: " + ("force-recomputing all embeddings" if force else "embedding documents that are missing embeddings"))

    db = SessionLocal()
    try:
        from sqlalchemy import and_, or_
        existing = embedded_ids()
        # Mirror the criterion from _run_embedding in services/indexer.py:
        # a document can be embedded if it has a summary OR ocr_text.
        embeddable = (
            db.query(Document)
            .filter(
                Document.is_deleted == False,
                or_(
                    and_(Document.summary.isnot(None), Document.summary != ""),
                    and_(Document.ocr_text.isnot(None), Document.ocr_text != ""),
                ),
            )
            .all()
        )
        if force:
            missing = embeddable
            _log(task_id,
                 f"Force mode: re-embedding all {len(missing)} embeddable document(s) "
                 f"({len(existing)} already had embeddings)")
        else:
            missing = [d for d in embeddable if d.id not in existing]
            _log(task_id,
                 f"Candidates: {len(missing)} document(s) missing embeddings "
                 f"({len(embeddable)} embeddable total, {len(existing)} already embedded)")
        total = len(missing)
        _set_progress(task_id, 0, total)

        processed = errors = 0
        for i, doc in enumerate(missing):
            if _is_stopped(task_id):
                _log(task_id, f"Stopped after {i} document(s)")
                return
            try:
                await _run_embedding(doc, db)
                db.commit()
                processed += 1
                _log(task_id, f"✓ {doc.filename}")
            except Exception as exc:
                errors += 1
                _log(task_id, f"✗ {doc.filename}: {exc}", "error")
            _set_progress(task_id, i + 1, total)
    finally:
        db.close()

    _finish(task_id, "done", {"processed": processed, "errors": errors, "candidates": total})
    _log(task_id, f"Done — embedded {processed} document(s), {errors} error(s)")


async def _fix_quality(task_id: int, config: dict) -> None:
    """Process documents that have a specific quality gap.

    Analysis gaps (no_analysis/no_summary/no_tags/no_category) are sent to
    Gemini Batch API via run_batch_analysis_gemini with an explicit doc_ids list.
    OCR and embedding gaps are handled sequentially as before.
    """
    from ..services.indexer import index_document, embed_document_by_id
    from sqlalchemy import or_, String

    quality = config.get("quality_filter", "")
    _log(task_id, f"Starting: fix quality gap '{quality}'")

    db = SessionLocal()
    try:
        base = db.query(Document).filter(Document.is_deleted == False)

        if quality == "no_ocr":
            docs = base.filter(
                or_(Document.ocr_status != "done", Document.ocr_text == None, Document.ocr_text == "")
            ).all()
            operation = "ocr"
        elif quality == "no_embedding":
            from ..services.embeddings import embedded_ids
            emb_ids = embedded_ids()
            docs = [d for d in base.all() if d.id not in emb_ids]
            operation = "embedding"
        elif quality == "no_analysis":
            docs = base.filter(Document.analysis_status != "done").all()
            operation = "batch_analysis"
        elif quality == "no_summary":
            docs = base.filter(or_(Document.summary == None, Document.summary == "")).all()
            operation = "batch_analysis"
        elif quality == "no_tags":
            docs = base.filter(or_(Document.tags == None, Document.tags.cast(String) == "[]")).all()
            operation = "batch_analysis"
        elif quality == "no_category":
            docs = base.filter(
                or_(
                    Document.document_type == None,
                    Document.document_type == "unclassified",
                    Document.document_type == "other",
                )
            ).all()
            operation = "batch_analysis"
        else:
            _log(task_id, f"Unknown quality_filter: {quality!r}", "error")
            _finish(task_id, "error")
            return

        total = len(docs)
        _log(task_id, f"Found {total} document(s) with gap: {quality!r}")
        _set_progress(task_id, 0, total)
        doc_ids = [d.id for d in docs]
        doc_names = {d.id: d.filename for d in docs}
    finally:
        db.close()

    if operation == "batch_analysis":
        if not doc_ids:
            _log(task_id, "No documents to process")
            _finish(task_id, "done", {"processed": 0})
            return
        _log(task_id, f"Delegating {len(doc_ids)} document(s) to Gemini Batch Analysis…")
        await run_batch_analysis_gemini(task_id, {**config, "doc_ids": doc_ids})
        return

    processed = errors = 0
    for i, doc_id in enumerate(doc_ids):
        if _is_stopped(task_id):
            _log(task_id, f"Stopped after {i} document(s)")
            return
        fname = doc_names.get(doc_id, str(doc_id))
        try:
            if operation == "ocr":
                await index_document(doc_id, True)
            else:
                await embed_document_by_id(doc_id)
            processed += 1
            _log(task_id, f"✓ {fname}")
        except Exception as exc:
            errors += 1
            _log(task_id, f"✗ {fname}: {exc}", "error")
        _set_progress(task_id, i + 1, total)

    _finish(task_id, "done", {"processed": processed, "errors": errors})
    _log(task_id, f"Done — {processed} document(s) processed, {errors} error(s)")


async def _cleanup_missing(task_id: int, config: dict) -> None:
    """Soft-delete DB entries whose files no longer exist on disk."""
    from pathlib import Path

    _log(task_id, "Scanning for missing files…")

    db = SessionLocal()
    try:
        docs = db.query(Document).filter(Document.is_deleted == False).all()
        total = len(docs)
        _set_progress(task_id, 0, total)
        _log(task_id, f"Checking {total} document(s)")

        removed = 0
        for i, doc in enumerate(docs):
            if _is_stopped(task_id):
                _log(task_id, f"Stopped after checking {i} document(s)")
                return
            if not Path(doc.filepath).exists():
                doc.is_deleted = True
                db.commit()
                removed += 1
                _log(task_id, f"✗ Missing — removed from DB: {doc.filename}")
            _set_progress(task_id, i + 1, total)
    finally:
        db.close()

    _finish(task_id, "done", {"checked": total, "removed": removed})
    _log(task_id, f"Done — checked {total}, removed {removed} missing file(s)")
