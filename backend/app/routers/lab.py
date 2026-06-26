"""
Lab router — OCR calibration screen endpoints. Prefix /api/lab.

All operations are ephemeral (no writes to the documents table). They run text
recognition on a single document's first page so the user can compare methods
and have a "premium" provider judge the results. See services/lab.py.
"""

import base64
from datetime import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, AIProvider
from ..services import lab
from ..services.ai_analysis import analyze_document
from ..services.ai_vision import VISION_CAPABLE
from ..schemas import (
    LabMethods, LabWorkerStatus, LabOcrRequest, LabOcrResult,
    LabVisionRequest, LabVisionResult,
    LabJudgeRequest, LabJudgeResult,
    LabSaveRequest, LabSaveResult,
    LabImageInfo, LabTransformRequest, LabPreviewResult, LabApplyResult,
)
from ..services.thumbnails import generate_thumbnail
from ..services.storage import compute_file_hash

router = APIRouter(prefix="/api/lab", tags=["lab"])


async def _auto_analyze(text: str, db: Session) -> dict | None:
    """Run text analysis on OCR output and return an ExtractedFields dict, or None."""
    if not text or not text.strip():
        return None
    try:
        result = await analyze_document(text, db)
        if result is None:
            return None
        return {
            "document_type": result.document_type,
            "document_date": result.document_date,
            "person_first_name": result.person_first_name,
            "person_last_name": result.person_last_name,
            "organization": result.organization,
            "amount": result.amount,
            "amount_currency": result.amount_currency,
            "language": result.language,
        }
    except Exception:
        return None


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
async def methods(db: Session = Depends(get_db)):
    status = await lab.worker_status(db)
    engines = ["tesseract"]
    if status["worker_available"]:
        engines.append("easyocr")
    return LabMethods(
        ocr_methods=engines,
        worker_available=status["worker_available"],
        worker_reachable=status["reachable"],
        worker_url=status["url"],
    )


@router.get("/worker-status", response_model=LabWorkerStatus)
async def get_worker_status(db: Session = Depends(get_db)):
    """Live health check of the compute worker."""
    status = await lab.worker_status(db)
    return LabWorkerStatus(**status)


@router.post("/ocr", response_model=LabOcrResult)
async def run_ocr(body: LabOcrRequest, db: Session = Depends(get_db)):
    img = _doc_image(body.doc_id, db)
    try:
        text, ms = await lab.run_local_ocr(img, body.method, db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OCR failed: {e}")
    fields = await _auto_analyze(text, db)
    return LabOcrResult(method=body.method, text=text, ms=ms, fields=fields)


@router.post("/vision", response_model=LabVisionResult)
async def run_vision(body: LabVisionRequest, db: Session = Depends(get_db)):
    provider = _provider(body.provider_id, db)
    if provider.provider_type not in VISION_CAPABLE:
        raise HTTPException(status_code=400, detail="Provider is not vision-capable")
    img = _doc_image(body.doc_id, db)
    try:
        text, fields, cost, ms, tin, tout = await lab.run_vision_ocr(img, provider, db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vision failed: {e}")
    # If vision returned no fields (e.g. Mistral OCR plain-text mode), fall back to text analysis
    if not fields:
        fields = await _auto_analyze(text, db)
    return LabVisionResult(
        provider_id=provider.id, name=provider.name,
        model_name=provider.model or None,
        text=text, fields=fields or None,
        cost=cost, ms=ms, tokens_in=tin, tokens_out=tout,
    )


@router.post("/save", response_model=LabSaveResult)
async def save_lab_result(body: LabSaveRequest, db: Session = Depends(get_db)):
    """
    Apply a lab recognition result to the document: saves OCR text, extracted fields,
    and attribution (which model produced the result).
    """
    from datetime import datetime as _dt
    doc = db.query(Document).filter(Document.id == body.doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.ocr_text = body.text
    doc.ocr_status = "done"
    doc.ocr_model = body.model_name
    doc.indexed_at = _dt.utcnow()

    f = body.fields or {}
    if f:
        if f.get("document_type"):
            doc.document_type = f["document_type"]
            doc.classification_source = "auto"
            doc.manually_classified = False
        if f.get("document_date"):
            try:
                doc.document_date = _dt.strptime(f["document_date"], "%Y-%m-%d")
            except Exception:
                pass
        if f.get("person_first_name") is not None:
            doc.person_first_name = f["person_first_name"] or None
        if f.get("person_last_name") is not None:
            doc.person_last_name = f["person_last_name"] or None
        if f.get("organization") is not None:
            doc.organization = f["organization"] or None
        if f.get("amount") is not None:
            try:
                doc.amount = float(f["amount"])
            except Exception:
                pass
        if f.get("amount_currency") is not None:
            doc.amount_currency = f["amount_currency"] or None
        if f.get("language"):
            doc.language = f["language"]
        doc.analysis_status = "done"

    db.commit()
    return LabSaveResult(ok=True, doc_id=doc.id)


@router.get("/{doc_id}/image-info", response_model=LabImageInfo)
async def image_info(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.filepath).exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    try:
        return LabImageInfo(**lab.get_image_info(doc.filepath))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read image: {e}")


@router.post("/{doc_id}/preview-transform", response_model=LabPreviewResult)
async def preview_transform_endpoint(doc_id: int, body: LabTransformRequest, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.filepath).exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    try:
        jpeg_bytes, w, h = lab.preview_transform(doc.filepath, body.crop, body.scale, body.quality)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Preview failed: {e}")
    return LabPreviewResult(
        image_b64=base64.b64encode(jpeg_bytes).decode(),
        width=w, height=h,
        file_size=len(jpeg_bytes),
    )


@router.post("/{doc_id}/apply-transform", response_model=LabApplyResult)
async def apply_transform_endpoint(doc_id: int, body: LabTransformRequest, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.filepath).exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    try:
        new_w, new_h, new_size = lab.apply_transform(doc.filepath, body.crop, body.scale, body.quality)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Apply failed: {e}")
    doc.file_size = new_size
    doc.file_hash = compute_file_hash(Path(doc.filepath))
    doc.updated_at = _dt.utcnow()
    db.commit()
    generate_thumbnail(doc.filepath, doc.id)
    return LabApplyResult(ok=True, doc_id=doc_id, width=new_w, height=new_h, file_size=new_size)


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
        result = await lab.judge(candidates, provider, db, img_bytes=img, language=body.language)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Judge failed: {e}")
    return LabJudgeResult(**result)
