from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional
from pathlib import Path

from ..database import get_db
from ..models import Document
from ..schemas import DocumentOut, DocumentList, FolderTreeNode, PatchTypeRequest, PatchDateRequest
from ..services.storage import infer_document_date
from ..services.folder_tree import build_folder_tree

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


@router.get("/tree", response_model=FolderTreeNode)
def get_folder_tree(db: Session = Depends(get_db)):
    """Full library folder structure for the Explorer-style folder-browse view."""
    return build_folder_tree(db)


@router.get("/tags", response_model=list[str])
def list_tags(db: Session = Depends(get_db)):
    """Distinct tags across the whole library, for tag-input autocomplete."""
    rows = db.query(Document.tags).filter(Document.is_deleted == False, Document.tags.isnot(None)).all()
    tag_set: set[str] = set()
    for (tags,) in rows:
        if tags:
            tag_set.update(tags)
    return sorted(tag_set)


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """Hard-delete a document: removes the source file, thumbnail, embedding, and DB row."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        Path(doc.filepath).unlink(missing_ok=True)
    except OSError:
        pass
    if doc.thumbnail_path:
        try:
            Path(doc.thumbnail_path).unlink(missing_ok=True)
        except OSError:
            pass

    from ..services.embeddings import delete_document as delete_embedding
    delete_embedding(doc_id)

    db.delete(doc)
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


@router.patch("/{doc_id}/date")
def update_date(doc_id: int, body: PatchDateRequest, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id, Document.is_deleted == False).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if body.date is not None:
        doc.document_date = body.date
    else:
        doc.document_date = infer_document_date(Path(doc.filepath))
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
    # no-cache on inline: browser must revalidate via ETag before serving from cache,
    # so after a transform the fresh file is shown immediately (304 if unchanged, 200 if not).
    headers = {"Cache-Control": "no-cache"} if inline else {}
    return FileResponse(
        path=str(path),
        filename=doc.filename,
        media_type=doc.mime_type or "application/octet-stream",
        content_disposition_type="inline" if inline else "attachment",
        headers=headers,
    )
