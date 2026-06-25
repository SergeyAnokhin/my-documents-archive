from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path
from datetime import datetime

from ..database import get_db
from ..models import AppSettings, Document, WatchedFolder, IndexingLog, AIProvider
from ..schemas import (
    FetchModelsRequest,
    IndexingStats,
    LogEntry,
    ProviderModelInfo,
    SyncResponse,
    WatchedFolderCreate,
    WatchedFolderOut,
    AIProviderCreate,
    AIProviderOut,
)
from ..services.storage import scan_library_for_new_files, compute_file_hash, guess_mime
from ..services.thumbnails import generate_thumbnail
from ..services.indexer import index_document, index_pending_batch, reclassify_pending_batch

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=IndexingStats)
def get_stats(db: Session = Depends(get_db)):
    base = db.query(Document).filter(Document.is_deleted == False)
    total    = base.count()
    indexed  = base.filter(Document.ocr_status == "done").count()
    analyzed = base.filter(Document.analysis_status == "done").count()
    pending  = base.filter(Document.ocr_status == "pending").count()
    errors   = base.filter(Document.ocr_status == "error").count()

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


# ── Watched Folders ───────────────────────────────────────────────────────────

@router.get("/folders", response_model=list[WatchedFolderOut])
def list_folders(db: Session = Depends(get_db)):
    return db.query(WatchedFolder).all()


@router.post("/folders", response_model=WatchedFolderOut, status_code=201)
def add_folder(body: WatchedFolderCreate, db: Session = Depends(get_db)):
    if not Path(body.path).exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    folder = WatchedFolder(path=body.path)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    from ..services.watcher import watcher
    watcher.reload()
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
def remove_folder(folder_id: int, db: Session = Depends(get_db)):
    f = db.query(WatchedFolder).filter(WatchedFolder.id == folder_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    db.delete(f)
    db.commit()
    from ..services.watcher import watcher
    watcher.reload()


@router.patch("/folders/{folder_id}/toggle")
def toggle_folder(folder_id: int, db: Session = Depends(get_db)):
    f = db.query(WatchedFolder).filter(WatchedFolder.id == folder_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    f.enabled = not f.enabled
    db.commit()
    db.refresh(f)
    from ..services.watcher import watcher
    watcher.reload()
    return WatchedFolderOut.model_validate(f)


# ── AI Providers ──────────────────────────────────────────────────────────────

@router.get("/providers", response_model=list[AIProviderOut])
def list_providers(db: Session = Depends(get_db)):
    return db.query(AIProvider).order_by(AIProvider.sort_order).all()


@router.post("/providers", response_model=AIProviderOut, status_code=201)
def add_provider(body: AIProviderCreate, db: Session = Depends(get_db)):
    data = body.model_dump()

    # Auto-assign sort_order: place after all existing providers
    if data.get("sort_order", 0) == 0:
        max_order = db.query(func.max(AIProvider.sort_order)).scalar() or 0
        data["sort_order"] = max_order + 10

    # Auto-generate name if left empty
    if not data.get("name"):
        model_part = data.get("model") or "default"
        key_label = data.get("key_name") or ""
        base = f"{data['provider_type']}/{model_part}"
        data["name"] = f"{base} [{key_label}]" if key_label else base

    p = AIProvider(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/providers/{provider_id}/toggle", response_model=AIProviderOut)
def toggle_provider(provider_id: int, db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    p.enabled = not p.enabled
    db.commit()
    db.refresh(p)
    return AIProviderOut.model_validate(p)


@router.patch("/providers/{provider_id}/order", response_model=AIProviderOut)
def update_provider_order(provider_id: int, body: dict, db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    p.sort_order = int(body.get("sort_order", p.sort_order))
    db.commit()
    db.refresh(p)
    return AIProviderOut.model_validate(p)


@router.patch("/providers/{provider_id}/settings", response_model=AIProviderOut)
def update_provider_settings(provider_id: int, body: dict, db: Session = Depends(get_db)):
    """Replace extra_params for a provider (fine-tuning options like image_policy, temperature)."""
    p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    # Strip None/empty values so the stored dict stays clean
    p.extra_params = {k: v for k, v in body.items() if v is not None and v != ""}
    db.commit()
    db.refresh(p)
    return AIProviderOut.model_validate(p)


@router.patch("/providers/{provider_id}/model", response_model=AIProviderOut)
def update_provider_model(provider_id: int, body: dict, db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    new_model = str(body.get("model", "")).strip()
    if not new_model:
        raise HTTPException(status_code=400, detail="model is required")
    p.model = new_model
    # Regenerate name: keep existing key_name bracket if present
    import re
    bracket = re.search(r"\[([^\]]+)\]$", p.name or "")
    key_label = bracket.group(1) if bracket else None
    base = f"{p.provider_type}/{new_model}"
    p.name = f"{base} [{key_label}]" if key_label else base
    db.commit()
    db.refresh(p)
    return AIProviderOut.model_validate(p)


@router.post("/providers/{provider_id}/models", response_model=list[ProviderModelInfo])
async def fetch_provider_models_by_id(provider_id: int, db: Session = Depends(get_db)):
    """Fetch available models for an existing provider using its stored API key."""
    p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    from ..services.provider_models import fetch_models
    models = await fetch_models(p.provider_type, p.api_key, p.base_url)
    return models


@router.delete("/providers/{provider_id}", status_code=204)
def remove_provider(provider_id: int, db: Session = Depends(get_db)):
    p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    db.delete(p)
    db.commit()


@router.post("/providers/models", response_model=list[ProviderModelInfo])
async def fetch_provider_models(body: FetchModelsRequest):
    """Fetch available model list from the given provider's API."""
    from ..services.provider_models import fetch_models
    models = await fetch_models(body.provider_type, body.api_key, body.base_url)
    return models


# ── Arena Ratings ─────────────────────────────────────────────────────────────

@router.get("/arena-ratings")
def get_arena_ratings(db: Session = Depends(get_db)):
    """Return cached LM Arena star ratings: {model_id: {text: 0-5, vision: 0-5}}."""
    from ..services.arena_ratings import get_cached
    return get_cached(db)


@router.post("/arena-ratings/refresh")
async def refresh_arena_ratings(db: Session = Depends(get_db)):
    """Fetch fresh ratings from LM Arena leaderboard and update cache."""
    from ..services.arena_ratings import refresh_ratings
    ratings = await refresh_ratings(db)
    return {"updated": len(ratings), "ratings": ratings}


# ── App Settings (key-value) ──────────────────────────────────────────────────

@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    """Return all app settings as {key: value} dict."""
    rows = db.query(AppSettings).all()
    return {r.key: r.value for r in rows}


@router.patch("/settings")
def update_settings(body: dict, db: Session = Depends(get_db)):
    """Upsert app settings. Body: {key: value, ...}"""
    for key, value in body.items():
        row = db.query(AppSettings).filter(AppSettings.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(AppSettings(key=key, value=str(value)))
    db.commit()
    rows = db.query(AppSettings).all()
    return {r.key: r.value for r in rows}


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
