"""DB backup admin endpoints (advanced users): list + restore + retention setting."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppSettings
from ..schemas import BackupInfo, BackupKeepUpdate, RestoreRequest
from ..services.db_backup import KEEP_MAX, KEEP_MIN, create_backup, get_keep_count, list_backups, restore_backup

router = APIRouter()


@router.get("/backups", response_model=list[BackupInfo])
def get_backups():
    return list_backups()


@router.post("/backups")
def post_create_backup(db: Session = Depends(get_db)):
    try:
        return create_backup(db)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/backups/restore")
def post_restore(req: RestoreRequest):
    try:
        return restore_backup(req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/backups/keep")
def get_backup_keep(db: Session = Depends(get_db)):
    return {"keep": get_keep_count(db), "min": KEEP_MIN, "max": KEEP_MAX}


@router.patch("/backups/keep")
def patch_backup_keep(body: BackupKeepUpdate, db: Session = Depends(get_db)):
    if not (KEEP_MIN <= body.keep <= KEEP_MAX):
        raise HTTPException(status_code=400, detail=f"keep must be between {KEEP_MIN} and {KEEP_MAX}")
    row = db.query(AppSettings).filter(AppSettings.key == "backup_keep").first()
    if row:
        row.value = str(body.keep)
    else:
        db.add(AppSettings(key="backup_keep", value=str(body.keep)))
    db.commit()
    return {"keep": body.keep}
