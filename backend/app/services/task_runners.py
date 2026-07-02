"""Background task runners + dispatcher for the Tasks panel.

Split out of routers/tasks.py to keep that router focused on CRUD/control
endpoints. This module owns `_run_task_bg` (the type→runner dispatcher),
`recover_running_tasks` (startup recovery of orphaned "running" rows), and
the short in-process runners. Long batch runners live in their own modules
(batch_ocr_mistral.py / batch_ocr_gemini.py / batch_analysis.py).
"""
import asyncio
from datetime import datetime

from ..database import SessionLocal
from ..models import Document, Task

from .task_runtime import (
    finish as _finish,
    is_stopped as _is_stopped,
    log_task as _log,
    set_progress as _set_progress,
)
from .batch_ocr_mistral import run_batch_ocr_mistral
from .batch_ocr_gemini import run_batch_ocr_gemini
from .batch_analysis import run_batch_analysis_gemini
from .image_compress import run_compress_images

# Task types that submit a remote batch job and can reconnect to it via
# batch_job_id (saved in Task.result_summary) instead of resubmitting.
BATCH_RESUMABLE_TYPES = (
    "batch_ocr_mistral", "batch_ocr_gemini", "batch_analysis_gemini",
    "reclassify_unclassified", "reclassify_all",
)


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


async def recover_running_tasks() -> None:
    """Recover Task rows stuck at status="running" after an unclean restart.

    Background runners execute as in-process asyncio coroutines (FastAPI
    BackgroundTasks) with no separate worker process — a pod restart kills
    them mid-flight without ever updating the Task row, so it stays at
    status="running" forever, which also blocks both the Run and Resume
    buttons in the UI. Called once at app startup (see main.py).

    Batch tasks that already had a remote job submitted (`batch_job_id` saved
    in result_summary) are auto-resumed — the remote job survives the
    restart, since it runs on the provider's servers, not in this process.
    Everything else is reset to "stopped" so the user can manually re-run it;
    any work already committed to the DB before the restart is preserved.
    """
    db = SessionLocal()
    try:
        orphaned = db.query(Task).filter(Task.status == "running").all()
        to_resume: list[tuple[int, str, dict]] = []
        to_note: list[int] = []
        for task in orphaned:
            batch_job_id = (task.result_summary or {}).get("batch_job_id")
            if task.task_type in BATCH_RESUMABLE_TYPES and batch_job_id:
                task.started_at = datetime.utcnow()
                task.finished_at = None
                to_resume.append((
                    task.id, task.task_type,
                    {**(task.config or {}), "resume_batch_job_id": str(batch_job_id)},
                ))
            else:
                task.status = "stopped"
                task.finished_at = datetime.utcnow()
                to_note.append(task.id)
        db.commit()
    finally:
        db.close()

    for task_id in to_note:
        _log(task_id, "⚠️ Backend restarted while this task was running — marked as stopped.", "warning")

    for task_id, task_type, config in to_resume:
        _log(task_id, "🔄 Backend restarted — auto-resuming, reconnecting to the remote batch job.")
        asyncio.create_task(_run_task_bg(task_id, task_type, config))


async def _index_unindexed(task_id: int, config: dict) -> None:
    from .indexer import index_document

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
    from .indexer import index_document
    from .storage import compute_file_hash, guess_mime, scan_library_for_new_files
    from .thumbnails import generate_thumbnail

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
    from .recluster import run_recluster

    max_clusters = int(config.get("max_clusters", 40))
    min_clusters = int(config.get("min_clusters", 2))
    provider_id = config.get("provider_id")
    provider_id = int(provider_id) if provider_id else None
    _log(task_id, f"Starting: cluster-based recategorization (min_clusters={min_clusters}, max_clusters={max_clusters})")
    result = await run_recluster(task_id=task_id, max_clusters=max_clusters, min_clusters=min_clusters, provider_id=provider_id)
    _finish(task_id, "done", result)
    _log(task_id, f"Done — {result.get('applied', 0)} documents in {result.get('clusters', 0)} clusters")


async def _embed_missing(task_id: int, config: dict) -> None:
    """Embed every analyzed document (summary present) that has no embedding yet.

    Scans the whole archive — not just freshly-added docs — so it backfills the
    vector index after it was reset or for documents analyzed before embeddings
    existed. Logs the candidate count up front.

    config.force=True re-embeds ALL analyzed documents, ignoring existing vectors.
    """
    from .indexer import _run_embedding
    from .embeddings import embedded_ids

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
    from .indexer import index_document, embed_document_by_id
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
            from .embeddings import embedded_ids
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
