"""
Lab router — OCR calibration screen endpoints. Prefix /api/lab.

All operations are ephemeral (no writes to the documents table). They run text
recognition on a single document's first page so the user can compare methods
and have a "premium" provider judge the results. See services/lab.py.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, AIProvider
from ..services import lab
from ..services.ai_vision import VISION_CAPABLE
from ..schemas import (
    LabMethods, LabOcrRequest, LabOcrResult,
    LabVisionRequest, LabVisionResult,
    LabJudgeRequest, LabJudgeResult,
)

router = APIRouter(prefix="/api/lab", tags=["lab"])


def _doc_image(doc_id: int, db: Session) -> bytes:
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.filepath).exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    try:
        return lab.load_image(doc.filepath)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot load image: {e}")


def _provider(provider_id: int, db: Session) -> AIProvider:
    p = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return p


@router.get("/methods", response_model=LabMethods)
async def methods():
    worker = await lab.worker_available()
    engines = ["tesseract"]
    if worker:
        engines.append("easyocr")
    return LabMethods(ocr_methods=engines, worker_available=worker)


@router.post("/ocr", response_model=LabOcrResult)
async def run_ocr(body: LabOcrRequest, db: Session = Depends(get_db)):
    img = _doc_image(body.doc_id, db)
    try:
        text, ms = await lab.run_local_ocr(img, body.method)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OCR failed: {e}")
    return LabOcrResult(method=body.method, text=text, ms=ms)


@router.post("/vision", response_model=LabVisionResult)
async def run_vision(body: LabVisionRequest, db: Session = Depends(get_db)):
    provider = _provider(body.provider_id, db)
    if provider.provider_type not in VISION_CAPABLE:
        raise HTTPException(status_code=400, detail="Provider is not vision-capable")
    img = _doc_image(body.doc_id, db)
    try:
        text, cost, ms = await lab.run_vision_ocr(img, provider, db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vision failed: {e}")
    return LabVisionResult(provider_id=provider.id, name=provider.name, text=text, cost=cost, ms=ms)


@router.post("/judge", response_model=LabJudgeResult)
async def run_judge(body: LabJudgeRequest, db: Session = Depends(get_db)):
    if len(body.candidates) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 transcriptions to compare")
    provider = _provider(body.provider_id, db)
    img = None
    if body.use_image:
        if provider.provider_type not in VISION_CAPABLE:
            raise HTTPException(status_code=400, detail="Provider cannot judge with an image")
        img = _doc_image(body.doc_id, db)
    candidates = [{"label": c.label, "text": c.text} for c in body.candidates]
    try:
        result = await lab.judge(candidates, provider, db, img_bytes=img)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Judge failed: {e}")
    return LabJudgeResult(**result)
