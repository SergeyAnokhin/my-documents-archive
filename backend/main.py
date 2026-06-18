"""FastAPI application — main entry point."""

import logging
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
from backend.database import get_db, init_db, engine, search_documents
from backend.models import Document, generate_uuid, file_hash
from backend.thumbnails import generate_thumbnail
from backend.indexer import index_document

logger = logging.getLogger(__name__)

app = FastAPI(title="DocIntel", version="0.2.0")

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
    """Upload a new document. Saves to documents dir, creates DB record,
    generates thumbnail, and runs OCR inline."""
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

    # Generate thumbnail (synchronous for now)
    try:
        thumb_path = generate_thumbnail(stored_path, doc_id)
        if thumb_path:
            doc.thumbnail_path = thumb_path
            db.commit()
            db.refresh(doc)
    except Exception:
        pass  # Non-critical

    # Run OCR (synchronous for now; Phase 5 will move to background)
    try:
        index_document(doc_id)
        db.refresh(doc)
    except Exception:
        pass  # OCR errors are stored on the document

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
        raise HTTPException(404, "No thumbnail available")
    return FileResponse(doc.thumbnail_path)


# ── Search (full-text + semantic) ──────────────────────

@app.get("/api/search")
def search_documents_endpoint(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    mode: str = Query("fulltext", regex="^(fulltext|semantic|hybrid)$"),
    db: Session = Depends(get_db),
):
    """Search documents by text or meaning.

    Modes:
      fulltext — FTS5 keyword search
      semantic — meaning-based via embeddings
      hybrid — combines both (best results first)"""

    if mode == "semantic":
        from backend.embeddings import semantic_search
        semantic_results = semantic_search(q, limit=limit)
        # Fetch document details for the found IDs
        ids = [r["id"] for r in semantic_results]
        docs = db.query(Document).filter(Document.id.in_(ids)).all() if ids else []
        doc_map = {d.id: d for d in docs}
        results = []
        for r in semantic_results:
            doc = doc_map.get(r["id"])
            if doc:
                d = doc.to_dict()
                d["_score"] = r["score"]
                results.append(d)
        return {"results": results, "total": len(results), "mode": "semantic"}

    elif mode == "hybrid":
        # Full-text results
        try:
            fts_results = search_documents(q, limit=limit)
        except Exception:
            fts_results = []
        # Semantic results
        from backend.embeddings import semantic_search
        semantic_results = semantic_search(q, limit=limit)

        # Score hybrid: both sources contribute
        seen: dict[str, dict] = {}
        for r in fts_results:
            seen[r["id"]] = {**r, "_score": 1.0}  # FTS match = high score
        for r in semantic_results:
            if r["id"] in seen:
                seen[r["id"]]["_score"] = (seen[r["id"]]["_score"] + r["score"]) / 2
            else:
                seen[r["id"]] = {"id": r["id"], "_score": r["score"] * 0.8}

        # Fetch docs for all found IDs
        docs = db.query(Document).filter(Document.id.in_(list(seen.keys()))).all()
        doc_map = {d.id: d for d in docs}

        results = []
        for doc_id, meta in sorted(seen.items(), key=lambda x: x[1]["_score"], reverse=True):
            doc = doc_map.get(doc_id)
            if doc:
                d = doc.to_dict()
                d["_score"] = round(meta["_score"], 4)
                results.append(d)

        return {"results": results[:limit], "total": len(results), "mode": "hybrid"}

    else:  # fulltext
        try:
            results = search_documents(q, limit=limit)
            return {"results": results, "total": len(results), "mode": "fulltext"}
        except Exception as e:
            return {"results": [], "total": 0, "error": str(e), "mode": "fulltext"}


# ── Indexing ────────────────────────────────────────────

@app.post("/api/documents/{doc_id}/reindex")
def reindex_document(doc_id: str, db: Session = Depends(get_db)):
    """Re-run OCR indexing for a single document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    from backend.models import IndexingStatus
    doc.ocr_status = IndexingStatus.pending
    db.commit()

    index_document(doc_id)
    db.refresh(doc)
    return doc.to_dict()


@app.post("/api/index/next")
def index_next(
    limit: int = Query(10, ge=1, le=100),
):
    """Process the next N pending documents."""
    from backend.indexer import index_next_batch
    processed = index_next_batch(limit)
    return {"processed": processed}


# ── Stats ───────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    from backend.models import IndexingStatus

    total = db.query(Document).count()
    indexed = (
        db.query(Document)
        .filter(Document.ocr_status == IndexingStatus.done)
        .count()
    )
    pending = (
        db.query(Document)
        .filter(Document.ocr_status == IndexingStatus.pending)
        .count()
    )
    errors = (
        db.query(Document)
        .filter(Document.ocr_status == IndexingStatus.error)
        .count()
    )
    return {
        "total": total,
        "indexed": indexed,
        "pending": pending,
        "errors": errors,
    }


# ── AI Configuration ────────────────────────────────────

@app.get("/api/ai-config")
def get_ai_config():
    """Get AI provider configuration."""
    from backend.config import get_ai_config as load_config
    return load_config()


@app.put("/api/ai-config")
async def update_ai_config(body: dict):
    """Update AI provider configuration."""
    from backend.config import save_ai_config, get_ai_config as load_config

    current = load_config()
    allowed = {"provider", "analysis_model", "analysis_enabled", "vision_model", "vision_enabled"}
    for key in allowed:
        if key in body:
            current[key] = body[key]
    save_ai_config(current)
    return current


# ── Re-analyze (AI only, skip OCR) ──────────────────────

@app.post("/api/documents/{doc_id}/reanalyze")
def reanalyze_document(doc_id: str, db: Session = Depends(get_db)):
    """Re-run AI analysis only (does not redo OCR)."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    from backend.models import IndexingStatus
    from backend.ai_analysis import analyze_document

    doc.analysis_status = IndexingStatus.pending
    db.commit()

    if doc.ocr_text and doc.ocr_text.strip():
        try:
            result = analyze_document(doc.ocr_text, doc.original_filename)
            doc.summary = result.get("summary", "")
            doc.tags = result.get("tags", [])
            doc.doc_type = result.get("doc_type", "")
            doc.doc_language = result.get("language", "")
            if result.get("doc_date"):
                from datetime import datetime
                try:
                    doc.doc_date = datetime.strptime(result["doc_date"], "%Y-%m-%d")
                except (ValueError, TypeError):
                    pass
            doc.analysis_status = IndexingStatus.done
        except Exception as e:
            doc.analysis_status = IndexingStatus.error
    db.commit()
    db.refresh(doc)
    return doc.to_dict()


# ── Batch AI Analysis ───────────────────────────────────

@app.post("/api/index/analyze")
def analyze_batch(limit: int = Query(10, ge=1, le=100)):
    """Run AI analysis on N documents that have OCR but no analysis."""
    from backend.indexer import index_next_batch
    processed = index_next_batch(limit)
    return {"processed": processed}


# ── Serve frontend (production) ─────────────────────────

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
