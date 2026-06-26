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


@router.get("/{task_id}/logs", response_model=List[TaskLogOut])
def get_task_logs(task_id: int, limit: int = 200, db: Session = Depends(get_db)):
    return (
        db.query(TaskLog)
        .filter(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.asc())
        .limit(limit)
        .all()
    )


# ── Background runners ────────────────────────────────────────────────────────

def _log(task_id: int, message: str, level: str = "info") -> None:
    db = SessionLocal()
    try:
        db.add(TaskLog(task_id=task_id, message=message, level=level))
        db.commit()
    finally:
        db.close()


def _is_stopped(task_id: int) -> bool:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        return task is None or task.status == "stopped"
    finally:
        db.close()


def _set_progress(task_id: int, current: int, total: int) -> None:
    db = SessionLocal()
    try:
        db.query(Task).filter(Task.id == task_id).update(
            {"progress_current": current, "progress_total": total}
        )
        db.commit()
    finally:
        db.close()


def _finish(task_id: int, status: str, result: dict | None = None) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.status != "stopped":
            task.status = status
            task.finished_at = datetime.utcnow()
            if result:
                task.result_summary = result
            db.commit()
    finally:
        db.close()


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
        elif task_type == "batch_ocr_mistral":
            await _batch_ocr_mistral(task_id, config)
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
                _log(task_id, f"✓ {doc.filename}")
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
    from ..services.indexer import reclassify_unclassified_batch

    limit = int(config.get("limit", 200))
    _log(task_id, f"Starting: re-classify up to {limit} unclassified document(s)")
    result = await reclassify_unclassified_batch(limit)
    _finish(task_id, "done", result if isinstance(result, dict) else {"result": str(result)})
    _log(task_id, f"Done — {result}")


async def _reclassify_all(task_id: int, config: dict) -> None:
    from ..services.indexer import reclassify_pending_batch

    limit = int(config.get("limit", 200))
    _log(task_id, f"Starting: re-classify up to {limit} document(s)")
    result = await reclassify_pending_batch(limit)
    _finish(task_id, "done", result if isinstance(result, dict) else {"result": str(result)})
    _log(task_id, f"Done — {result}")


async def _batch_ocr_mistral(task_id: int, config: dict) -> None:
    """
    Mistral Batch OCR — uses Mistral's Batch API (50 % cheaper, async).

    Flow:
      1. Load first page of each pending document as JPEG.
      2. Build a JSONL file with inline-base64 OCR requests.
      3. Upload JSONL to Mistral Files API.
      4. Create a batch job pointing at that file.
      5. Poll every `poll_interval` seconds until the job completes.
      6. Download the output file and save OCR text back to each document.
    """
    import asyncio
    import base64
    import json

    import httpx

    from ..models import AIProvider
    from ..services.ai_vision import load_first_page, parse_mistral_ocr

    limit = int(config.get("limit", 50))
    provider_id = config.get("provider_id")
    poll_interval = int(config.get("poll_interval", 300))

    # ── 1. Resolve Mistral provider ──────────────────────────────────────────
    db = SessionLocal()
    try:
        if provider_id:
            provider = db.query(AIProvider).filter(
                AIProvider.id == int(provider_id),
                AIProvider.provider_type == "mistral",
            ).first()
        else:
            provider = None

        if not provider:
            provider = db.query(AIProvider).filter(
                AIProvider.provider_type == "mistral",
                AIProvider.enabled == True,
            ).order_by(AIProvider.sort_order).first()

        if not provider:
            _log(task_id, "No Mistral provider configured — add one in AI Settings", "error")
            _finish(task_id, "error")
            return

        api_key = provider.api_key
        model = provider.model or "mistral-ocr-latest"
        image_policy = (provider.extra_params or {}).get("image_policy", "placeholder")

        # ── 2. Collect pending documents ─────────────────────────────────────
        docs = (
            db.query(Document)
            .filter(Document.ocr_status == "pending", Document.is_deleted == False)
            .limit(limit)
            .all()
        )
        total = len(docs)
    finally:
        db.close()

    if total == 0:
        _log(task_id, "No pending documents found")
        _finish(task_id, "done", {"processed": 0})
        return

    _log(task_id, f"Found {total} document(s) — model: {model}")
    _set_progress(task_id, 0, total)

    # ── 3. Build JSONL (inline base64) ───────────────────────────────────────
    _log(task_id, "Loading document images…")
    jsonl_lines: list[str] = []
    doc_id_map: dict[str, int] = {}   # custom_id (str doc.id) → doc.id

    for i, doc in enumerate(docs):
        if _is_stopped(task_id):
            _log(task_id, f"Stopped during image loading after {i} document(s)")
            return
        try:
            img_bytes = load_first_page(doc.filepath)
            b64 = base64.b64encode(img_bytes).decode()
            custom_id = str(doc.id)
            doc_id_map[custom_id] = doc.id
            jsonl_lines.append(json.dumps({
                "custom_id": custom_id,
                "body": {
                    "model": model,
                    "document": {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{b64}",
                    },
                    "include_image_base64": False,
                },
            }))
            _log(task_id, f"✓ Loaded: {doc.filename}")
        except Exception as exc:
            _log(task_id, f"✗ {doc.filename}: cannot load image — {exc}", "error")
        _set_progress(task_id, i + 1, total)

    if not jsonl_lines:
        _log(task_id, "No document images could be loaded", "error")
        _finish(task_id, "error")
        return

    # ── 4. Upload JSONL to Mistral Files API ─────────────────────────────────
    _log(task_id, f"Uploading batch ({len(jsonl_lines)} requests) to Mistral…")
    jsonl_bytes = "\n".join(jsonl_lines).encode()

    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=180) as client:
        upload_resp = await client.post(
            "https://api.mistral.ai/v1/files",
            headers=headers,
            files={"file": ("batch_ocr.jsonl", jsonl_bytes, "application/jsonl")},
            data={"purpose": "batch"},
        )
        upload_resp.raise_for_status()
        input_file_id = upload_resp.json()["id"]

    _log(task_id, f"Uploaded input file: {input_file_id}")

    # ── 5. Create batch job ──────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=60) as client:
        batch_resp = await client.post(
            "https://api.mistral.ai/v1/batch/jobs",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "input_files": [input_file_id],
                "endpoint": "/v1/ocr",
                "model": model,
            },
        )
        batch_resp.raise_for_status()
        batch_data = batch_resp.json()

    batch_job_id = batch_data["id"]
    _log(task_id, f"Batch job created: {batch_job_id}")

    # Save job ID so it's visible in result_summary during polling
    db = SessionLocal()
    try:
        task_row = db.query(Task).filter(Task.id == task_id).first()
        if task_row:
            task_row.result_summary = {
                "phase": "polling",
                "batch_job_id": batch_job_id,
                "doc_count": len(jsonl_lines),
            }
            db.commit()
    finally:
        db.close()

    # ── 6. Poll until complete ────────────────────────────────────────────────
    _log(task_id, f"Job submitted. Polling every {poll_interval}s… (up to 24 h)")

    while True:
        await asyncio.sleep(poll_interval)

        if _is_stopped(task_id):
            _log(task_id, f"Stopped by user. Batch job {batch_job_id} is still running on Mistral.")
            return

        async with httpx.AsyncClient(timeout=30) as client:
            status_resp = await client.get(
                f"https://api.mistral.ai/v1/batch/jobs/{batch_job_id}",
                headers=headers,
            )
            status_resp.raise_for_status()
            job_data = status_resp.json()

        job_status = job_data.get("status", "UNKNOWN")
        succeeded = job_data.get("succeeded_requests", 0)
        failed_req = job_data.get("failed_requests", 0)
        _log(task_id, f"Status: {job_status} — succeeded: {succeeded}, failed: {failed_req}")

        if job_status == "SUCCESS":
            break
        if job_status in ("FAILED", "CANCELLED", "TIMEOUT_EXCEEDED"):
            _log(task_id, f"Batch job ended with status: {job_status}", "error")
            _finish(task_id, "error", {"batch_job_id": batch_job_id, "status": job_status})
            return
        # Still pending (QUEUED / RUNNING / VALIDATING) — keep polling

    # ── 7. Download and parse results ────────────────────────────────────────
    output_file_id = job_data.get("output_file")
    if not output_file_id:
        _log(task_id, "Batch completed but no output_file in response", "error")
        _finish(task_id, "error")
        return

    _log(task_id, f"Downloading results from {output_file_id}…")
    async with httpx.AsyncClient(timeout=180) as client:
        results_resp = await client.get(
            f"https://api.mistral.ai/v1/files/{output_file_id}/content",
            headers=headers,
        )
        results_resp.raise_for_status()
        results_text = results_resp.text

    # ── 8. Save OCR text to documents ────────────────────────────────────────
    _log(task_id, "Saving OCR results to documents…")
    processed = 0
    failed_count = 0
    total_cost = 0.0

    db = SessionLocal()
    try:
        for line in results_text.strip().splitlines():
            if not line.strip():
                continue
            try:
                result_obj = json.loads(line)
                custom_id = result_obj.get("custom_id", "")
                doc_id = doc_id_map.get(custom_id)
                if not doc_id:
                    continue

                if result_obj.get("error"):
                    err_msg = result_obj["error"].get("message", "Unknown Mistral error")
                    _log(task_id, f"✗ Doc {doc_id}: {err_msg}", "error")
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.ocr_status = "error"
                        doc.ocr_error = err_msg
                        db.commit()
                    failed_count += 1
                    continue

                # response.body = OCR response dict
                ocr_body = (result_obj.get("response") or {}).get("body") or {}
                text, cost = parse_mistral_ocr(ocr_body, image_policy)
                total_cost += cost

                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.ocr_text = text
                    doc.ocr_status = "done"
                    doc.ocr_model = f"{model} (batch)"
                    doc.api_cost_vision = (doc.api_cost_vision or 0.0) + cost
                    db.commit()
                    _log(task_id, f"✓ Saved OCR for doc {doc_id}")
                    processed += 1

            except Exception as exc:
                _log(task_id, f"✗ Result parse error: {exc}", "error")
                failed_count += 1
    finally:
        db.close()

    summary = {
        "processed": processed,
        "failed": failed_count,
        "cost_usd": round(total_cost, 5),
        "batch_job_id": batch_job_id,
    }
    _finish(task_id, "done", summary)
    _log(task_id, (
        f"Done — {processed} saved, {failed_count} failed, "
        f"cost ${total_cost:.5f} (batch discount applied)"
    ))
