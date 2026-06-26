"""Watched-folder admin endpoints: list, add, remove, toggle."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import WatchedFolder
from ..schemas import WatchedFolderCreate, WatchedFolderOut

router = APIRouter()


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
