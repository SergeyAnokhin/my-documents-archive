from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional
from pathlib import Path

from ..database import get_db
from ..models import Document
from ..schemas import DocumentOut, DocumentList, PatchTypeRequest

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=DocumentList)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    year: Optional[int] = None,
    month: Optional[int] = None,
    document_type: Optional[str] = None,
    language: Optional[str] = None,
    ocr_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Document).filter(Document.is_deleted == False)

    if year:
        from sqlalchemy import extract
        q = q.filter(extract("year", Document.added_at) == year)
    if month:
        from sqlalchemy import extract
        q = q.filter(extract("month", Document.added_at) == month)
    if document_type:
        q = q.filter(Document.document_type == document_type)
    if language:
        q = q.filter(Document.language == language)
    if ocr_status:
        q = q.filter(Document.ocr_status == ocr_status)

    total = q.count()
    items = (
        q.order_by(Document.added_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return DocumentList(items=items, total=total, page=page, page_size=page_size)


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.is_deleted = True
    db.commit()


@router.patch("/{doc_id}/type")
def update_type(doc_id: int, body: PatchTypeRequest, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.document_type = body.document_type.strip()
    doc.manually_classified = True
    doc.classification_source = "manual"
    db.commit()
    db.refresh(doc)
    return DocumentOut.model_validate(doc)


@router.patch("/{doc_id}/tags")
def update_tags(doc_id: int, tags: list[str], db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.tags = tags
    db.commit()
    db.refresh(doc)
    return DocumentOut.model_validate(doc)


@router.get("/{doc_id}/download")
def download_document(doc_id: int, inline: bool = False, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(doc.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    # inline=1 lets the OCR Lab embed PDFs/images instead of forcing a download.
    return FileResponse(
        path=str(path),
        filename=doc.filename,
        media_type=doc.mime_type or "application/octet-stream",
        content_disposition_type="inline" if inline else "attachment",
    )
