"""App settings admin endpoints: key-value get/upsert + custom type-icon management."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppSettings
from ..services.type_icon_suggestion import (
    get_custom_type_icons,
    get_pending_custom_types,
    suggest_icons_for_types,
)

router = APIRouter()


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


@router.get("/type-icons")
def get_type_icons(db: Session = Depends(get_db)):
    """Return the custom type → Lucide icon name mapping."""
    return get_custom_type_icons(db)


@router.post("/update-type-icons")
async def update_type_icons(db: Session = Depends(get_db)):
    """Ask the LLM to assign Lucide icons to custom document types without one.

    Processes all distinct document_type values in the library that are not
    in the built-in taxonomy and have no custom icon yet.
    Returns {updated: N, icons: {type_slug: icon_name}}.
    """
    pending = get_pending_custom_types(db)
    if not pending:
        return {"updated": 0, "icons": get_custom_type_icons(db)}

    newly = await suggest_icons_for_types(pending, db)
    return {"updated": len(newly), "icons": get_custom_type_icons(db)}
