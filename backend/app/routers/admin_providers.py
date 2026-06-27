"""AI provider admin endpoints: CRUD, model listing, arena ratings."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import AIProvider
from ..schemas import (
    FetchModelsRequest,
    ProviderModelInfo,
    AIProviderCreate,
    AIProviderOut,
    AIProviderFull,
    ProvidersExport,
    ProvidersImport,
)

router = APIRouter()


# ── Export / Import (full config incl. API keys) ──────────────────────────────

@router.get("/providers/export", response_model=ProvidersExport)
def export_providers(db: Session = Depends(get_db)):
    """Download all AI providers, API keys included, for backup or migration."""
    providers = db.query(AIProvider).order_by(AIProvider.sort_order).all()
    return ProvidersExport(
        version=1,
        providers=[AIProviderFull.model_validate(p) for p in providers],
    )


@router.post("/providers/import")
def import_providers(body: ProvidersImport, db: Session = Depends(get_db)):
    """Restore AI providers from an exported config.

    replace=True wipes the current provider list first; otherwise the imported
    providers are appended after the existing ones.
    """
    if body.replace:
        db.query(AIProvider).delete()
        db.commit()

    base_order = db.query(func.max(AIProvider.sort_order)).scalar() or 0
    imported = 0
    for i, p in enumerate(body.providers):
        data = p.model_dump()
        if not body.replace:
            data["sort_order"] = base_order + (i + 1) * 10
        db.add(AIProvider(**data))
        imported += 1
    db.commit()
    return {"imported": imported, "replaced": body.replace}


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
