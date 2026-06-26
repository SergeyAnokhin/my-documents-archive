import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document
from ..schemas import UploadResponse
from ..services.storage import (
    compute_file_hash,
    guess_mime,
    is_supported,
    save_uploaded_file,
)
from ..services.thumbnails import generate_thumbnail
from ..services.indexer import index_document

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    path = Path(file.filename)
    if not is_supported(path):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {path.suffix}",
        )

    # Save to temp, compute hash, then move to library
    with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        file_hash = compute_file_hash(tmp_path)

        # Duplicate check
        existing = db.query(Document).filter(Document.file_hash == file_hash).first()
        if existing and not existing.is_deleted:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail=f"Document already exists (id={existing.id})",
            )

        dest = save_uploaded_file(tmp_path, file.filename)
        mime = guess_mime(dest)

        doc = Document(
            filename=dest.name,
            filepath=str(dest),
            file_hash=file_hash,
            file_size=dest.stat().st_size,
            mime_type=mime,
            ocr_status="pending",
            vision_status="pending",
            analysis_status="pending",
            source="upload",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Quick thumbnail sync (fast path — no OCR yet)
        thumb = generate_thumbnail(str(dest), doc.id)
        if thumb:
            doc.thumbnail_path = thumb
            db.commit()

        doc_id = doc.id

    finally:
        tmp_path.unlink(missing_ok=True)

    # Kick off OCR + full indexing in the background
    background_tasks.add_task(index_document, doc_id)

    return UploadResponse(
        document_id=doc_id,
        filename=doc.filename,
        message="Document uploaded — indexing started",
    )
