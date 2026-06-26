"""App settings admin endpoints: key-value get/upsert."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppSettings

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
