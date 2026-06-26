"""DB backup admin endpoints (advanced users): list + restore."""
from fastapi import APIRouter, HTTPException

from ..schemas import BackupInfo, RestoreRequest
from ..services.db_backup import list_backups, restore_backup

router = APIRouter()


@router.get("/backups", response_model=list[BackupInfo])
def get_backups():
    return list_backups()


@router.post("/backups/restore")
def post_restore(req: RestoreRequest):
    try:
        return restore_backup(req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
