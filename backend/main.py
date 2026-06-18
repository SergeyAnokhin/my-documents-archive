"""FastAPI application — main entry point."""

import os
import shutil
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.config import (
    DOCUMENTS_DIR,
    SUPPORTED_FORMATS,
    THUMBNAILS_DIR,
)
from backend.database import get_db, init_db, engine
from backend.models import Document, generate_uuid, file_hash


app = FastAPI(title="DocIntel", version="0.1.0")

# CORS — allow frontend on any port during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ── Upload ──────────────────────────────────────────────

@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a new document. Saves to documents dir, creates DB record."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise HTTPException(
            400,
            f"Unsupported format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    # Save file
    doc_id = generate_uuid()
    stored_name = f"{doc_id}{ext}"
    stored_path = DOCUMENTS_DIR / stored_name
    stored_path.write_bytes(content)

    fhash = file_hash(content)

    # Check for duplicate
    existing = db.query(Document).filter(Document.file_hash == fhash).first()
    if existing:
        # Remove the just-saved duplicate
        stored_path.unlink(missing_ok=True)
        raise HTTPException(409, f"Duplicate — already exists as '{existing.original_filename}'")

    doc = Document(
        id=doc_id,
        filename=stored_name,
        original_filename=file.filename,
        file_path=str(stored_path.resolve()),
        file_hash=fhash,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return doc.to_dict()


# ── List / Browse ───────────────────────────────────────

@app.get("/api/documents")
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List documents, newest first."""
    total = db.query(Document).count()
    docs = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "documents": [d.to_dict() for d in docs],
        "total": total,
    }


# ── Single Document ─────────────────────────────────────

@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db)):
    """Get a single document by ID."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc.to_dict()


# ── Download original file ──────────────────────────────

@app.get("/api/documents/{doc_id}/download")
def download_document(doc_id: str, db: Session = Depends(get_db)):
    """Download the original file."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    path = Path(doc.file_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(
        path,
        filename=doc.original_filename,
        media_type=doc.mime_type,
    )


# ── Thumbnail ───────────────────────────────────────────

@app.get("/api/documents/{doc_id}/thumbnail")
def get_thumbnail(doc_id: str, db: Session = Depends(get_db)):
    """Return the document's thumbnail image."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.thumbnail_path or not Path(doc.thumbnail_path).exists():
        # Return a placeholder
        raise HTTPException(404, "No thumbnail available")
    return FileResponse(doc.thumbnail_path)


# ── Stats ───────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    from backend.models import IndexingStatus

    total = db.query(Document).count()
    indexed = (
        db.query(Document)
        .filter(
            Document.ocr_status == IndexingStatus.done,
        )
        .count()
    )
    pending = (
        db.query(Document)
        .filter(
            Document.ocr_status == IndexingStatus.pending,
        )
        .count()
    )
    errors = (
        db.query(Document)
        .filter(
            Document.ocr_status == IndexingStatus.error,
        )
        .count()
    )
    return {
        "total": total,
        "indexed": indexed,
        "pending": pending,
        "errors": errors,
    }


# ── Serve frontend (production) ─────────────────────────

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
