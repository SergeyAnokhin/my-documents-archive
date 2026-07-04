"""Tasks API — create, run, stop, and inspect background processing jobs.

Endpoints only. The runners, the type→runner dispatcher (`_run_task_bg`) and
startup recovery (`recover_running_tasks`) live in services/task_runners.py.
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, Task, TaskLog
from ..schemas import TaskCreate, TaskLogOut, TaskOut, TaskUpdate
from ..services.task_runners import BATCH_RESUMABLE_TYPES, _run_task_bg

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[TaskOut])
def list_tasks(db: Session = Depends(get_db)):
    return db.query(Task).order_by(Task.sort_order.asc(), Task.id.asc()).all()


@router.post("", response_model=TaskOut)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    if body.task_type == "index_documents":
        strategy = (body.config or {}).get("strategy", "mistral_gemini")
        from ..services.indexing_plan import STRATEGIES
        if strategy not in STRATEGIES:
            raise HTTPException(400, "Unknown indexing strategy")
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
        Document.manually_classified != True,
        or_(Document.summary.isnot(None), Document.ocr_text.isnot(None)),
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
        "index_documents": base.filter(Document.analysis_status != "done").count(),
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


@router.get("/index-plan")
def get_index_plan(
    strategy: str = "mistral_gemini",
    limit: int = 500,
    gemini_provider_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Preview lazy routing and approximate provider cost without changing documents."""
    from ..services.indexing_plan import build_index_plan
    try:
        return build_index_plan(db, strategy, limit, gemini_provider_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


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
    if task.task_type not in BATCH_RESUMABLE_TYPES:
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
