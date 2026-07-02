"""Search endpoints: fulltext/semantic/hybrid search + AI Q&A (/ask).

Query-building helpers live in services/search_query.py; the /ask pipeline
lives in services/qa.py — this router only parses params and shapes responses.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, extract, func, String
from typing import Optional
import logging
import os
import time

log = logging.getLogger(__name__)

from ..database import get_db
from ..models import Document
from ..schemas import SearchResponse, SearchResult, DocumentOut, AIAnswerResponse
from ..services.search_query import (
    _apply_text_filter,
    _fulltext_ids,
    _highlight,
    _merge_hybrid,
    _parse_query,
    _semantic_scored,
)
from ..services import qa

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search_documents(
    query: str = Query(""),
    mode: str  = Query("fulltext"),
    year:          Optional[int] = None,
    month:         Optional[int] = None,
    document_type: Optional[str] = None,
    tag:           Optional[str] = None,
    folder:        Optional[str] = None,
    language:      Optional[str] = None,
    ocr_status:    Optional[str] = None,
    quality:       Optional[str] = None,
    page:      int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    base = db.query(Document).filter(Document.is_deleted == False)

    # ── Metadata filters (apply to all modes) ──────────────────────────────
    if year:
        date_col = func.coalesce(Document.document_date, Document.added_at)
        base = base.filter(extract("year", date_col) == year)
    if month:
        date_col = func.coalesce(Document.document_date, Document.added_at)
        base = base.filter(extract("month", date_col) == month)
    if document_type:
        base = base.filter(Document.document_type == document_type)
    if language:
        base = base.filter(Document.language == language)
    if ocr_status:
        base = base.filter(Document.ocr_status == ocr_status)
    if tag:
        base = base.filter(Document.tags.contains(tag))
    if folder:
        # `folder` is the relative directory path (forward-slash separated, as
        # returned by DocumentOut.relative_path). Match it as a path segment of
        # the absolute filepath, regardless of the OS path separator on disk.
        folder_native = folder.strip("/").replace("/", os.sep)
        if folder_native:
            base = base.filter(Document.filepath.contains(f"{os.sep}{folder_native}{os.sep}"))

    # ── Quality / status filters (advanced mode) ───────────────────────────
    if quality == "no_embedding":
        try:
            from ..services.embeddings import embedded_ids as get_embedded_ids
            emb_ids = get_embedded_ids()
            base = base.filter(~Document.id.in_(emb_ids))
        except Exception:
            pass
    elif quality == "no_ocr":
        base = base.filter(
            or_(
                Document.ocr_status != "done",
                Document.ocr_text == None,
                Document.ocr_text == "",
            )
        )
    elif quality == "no_analysis":
        base = base.filter(Document.analysis_status != "done")
    elif quality == "no_summary":
        base = base.filter(or_(Document.summary == None, Document.summary == ""))
    elif quality == "no_tags":
        base = base.filter(
            or_(Document.tags == None, Document.tags.cast(String) == "[]")
        )
    elif quality == "no_category":
        base = base.filter(
            or_(
                Document.document_type == None,
                Document.document_type == "unclassified",
                Document.document_type == "other",
            )
        )
    elif quality == "complete":
        base = base.filter(
            Document.analysis_status == "done",
            Document.summary != None,
            Document.summary != "",
            ~or_(Document.tags == None, Document.tags.cast(String) == "[]"),
            Document.document_type != None,
            Document.document_type != "unclassified",
        )

    t0 = time.perf_counter()

    # ── Semantic / hybrid ──────────────────────────────────────────────────
    if mode in ("semantic", "hybrid") and query:
        t1 = time.perf_counter()
        sem_scored_list = _semantic_scored(query, page_size * 4)
        sem_ids = [sid for sid, _ in sem_scored_list]
        sem_score_map = {sid: 1.0 - dist for sid, dist in sem_scored_list}
        log.debug("🧠 [search] semantic  ids=%d  ms=%.0f", len(sem_ids), (time.perf_counter() - t1) * 1000)

        if mode == "hybrid":
            t2 = time.perf_counter()
            ft_ids = _fulltext_ids(base, query)
            log.debug("📄 [search] fulltext  ids=%d  ms=%.0f", len(ft_ids), (time.perf_counter() - t2) * 1000)
            ordered_ids = _merge_hybrid(sem_ids, ft_ids)
        else:
            ordered_ids = sem_ids

        if ordered_ids:
            docs_all = (
                base.filter(Document.id.in_(ordered_ids))
                .order_by(Document.added_at.desc())
                .all()
            )
            # Re-sort by similarity order
            rank = {did: i for i, did in enumerate(ordered_ids)}
            docs_all.sort(key=lambda d: rank.get(d.id, 9999))

            total = len(docs_all)
            docs  = docs_all[(page - 1) * page_size: page * page_size]
            log.info("✅ [search] done  mode=%s  query=%r  results=%d  ms=%.0f",
                     mode, query[:60], total, (time.perf_counter() - t0) * 1000)
            return _build_response(docs, total, page, page_size, mode, query, sem_score_map)
        # Fall through to fulltext if no embeddings yet

    # ── Full-text (default + fallback) ─────────────────────────────────────
    q = base
    if query:
        phrases, words = _parse_query(query)
        q = _apply_text_filter(q, phrases, words)

    total = q.count()
    docs  = (
        q.order_by(Document.added_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    if query:
        log.info("✅ [search] done  mode=fulltext  query=%r  results=%d  ms=%.0f",
                 query[:60], total, (time.perf_counter() - t0) * 1000)
    return _build_response(docs, total, page, page_size, mode, query)


def _build_response(
    docs: list,
    total: int,
    page: int,
    page_size: int,
    mode: str,
    query: str,
    score_map: Optional[dict[int, float]] = None,
) -> SearchResponse:
    results = [
        SearchResult(
            document=DocumentOut.model_validate(d),
            score=score_map.get(d.id, 0.0) if score_map else 0.0,
            highlight=_highlight(d.ocr_text or d.summary, query),
        )
        for d in docs
    ]
    return SearchResponse(
        items=results,
        total=total,
        page=page,
        page_size=page_size,
        mode=mode,
    )


@router.get("/embedded-ids")
def get_embedded_ids():
    """Return the set of document IDs that have embeddings in ChromaDB."""
    from ..services.embeddings import embedded_ids
    return {"ids": sorted(embedded_ids())}


@router.get("/quality-counts")
def get_quality_counts(db: Session = Depends(get_db)):
    """Return document counts for each quality filter (for display in the dropdown)."""
    base = db.query(Document).filter(Document.is_deleted == False)

    no_ocr = base.filter(
        or_(
            Document.ocr_status != "done",
            Document.ocr_text == None,
            Document.ocr_text == "",
        )
    ).count()

    no_analysis = base.filter(Document.analysis_status != "done").count()

    no_summary = base.filter(
        or_(Document.summary == None, Document.summary == "")
    ).count()

    no_tags = base.filter(
        or_(Document.tags == None, Document.tags.cast(String) == "[]")
    ).count()

    no_category = base.filter(
        or_(
            Document.document_type == None,
            Document.document_type == "unclassified",
            Document.document_type == "other",
        )
    ).count()

    try:
        from ..services.embeddings import embedded_ids as get_embedded_ids
        emb_ids = get_embedded_ids()
        no_embedding = base.filter(~Document.id.in_(emb_ids)).count()
    except Exception:
        no_embedding = 0

    return {
        "no_ocr": no_ocr,
        "no_embedding": no_embedding,
        "no_analysis": no_analysis,
        "no_summary": no_summary,
        "no_tags": no_tags,
        "no_category": no_category,
    }


@router.get("/ask", response_model=AIAnswerResponse)
async def ask_documents(
    query: str = Query(""),
    language: str = Query("en"),
    year: Optional[int] = None,
    filter_language: Optional[str] = None,
    depth: int = Query(2, ge=1, le=3),
    debug: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Answer a free-form question about the user's documents using AI."""
    return await qa.answer_question(
        db, query,
        language=language,
        year=year,
        filter_language=filter_language,
        depth=depth,
        debug=debug,
    )
