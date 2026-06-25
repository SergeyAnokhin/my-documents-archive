from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, extract, String
from typing import Optional
import re

from ..database import get_db
from ..models import Document, AIProvider
from ..schemas import SearchResponse, SearchResult, DocumentOut, AIAnswerResponse

router = APIRouter(prefix="/api/search", tags=["search"])


def _highlight(text: Optional[str], query: str) -> Optional[str]:
    """Extract a ~200 char snippet around the first query hit."""
    if not text or not query:
        return None
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return text[:200]
    start = max(0, m.start() - 80)
    end   = min(len(text), m.end() + 120)
    snippet = text[start:end]
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


@router.get("", response_model=SearchResponse)
def search_documents(
    query: str = Query(""),
    mode: str  = Query("fulltext"),
    year:          Optional[int] = None,
    month:         Optional[int] = None,
    document_type: Optional[str] = None,
    tag:           Optional[str] = None,
    language:      Optional[str] = None,
    ocr_status:    Optional[str] = None,
    page:      int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    base = db.query(Document).filter(Document.is_deleted == False)

    # ── Metadata filters (apply to all modes) ──────────────────────────────
    if year:
        base = base.filter(extract("year", Document.added_at) == year)
    if month:
        base = base.filter(extract("month", Document.added_at) == month)
    if document_type:
        base = base.filter(Document.document_type == document_type)
    if language:
        base = base.filter(Document.language == language)
    if ocr_status:
        base = base.filter(Document.ocr_status == ocr_status)
    if tag:
        base = base.filter(Document.tags.contains(tag))

    # ── Semantic / hybrid ──────────────────────────────────────────────────
    if mode in ("semantic", "hybrid") and query:
        sem_ids = _semantic_ids(query, page_size * 4)

        if mode == "hybrid":
            ft_ids = _fulltext_ids(base, query)
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
            return _build_response(docs, total, page, page_size, mode, query)
        # Fall through to fulltext if no embeddings yet

    # ── Full-text (default + fallback) ─────────────────────────────────────
    q = base
    if query:
        terms = [t.strip() for t in query.split() if t.strip()]
        for term in terms:
            like = f"%{term}%"
            q = q.filter(or_(
                Document.filename.ilike(like),
                Document.ocr_text.ilike(like),
                Document.summary.ilike(like),
                Document.document_type.ilike(like),
                Document.tags.cast(String).ilike(like),
                Document.person_first_name.ilike(like),
                Document.person_last_name.ilike(like),
                Document.organization.ilike(like),
            ))

    total = q.count()
    docs  = (
        q.order_by(Document.added_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return _build_response(docs, total, page, page_size, mode, query)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _semantic_ids(query: str, n: int) -> list[int]:
    try:
        from ..services.embeddings import search_similar
        return search_similar(query, n_results=n)
    except Exception:
        return []


def _fulltext_ids(base_query, query: str) -> set[int]:
    q = base_query
    terms = [t.strip() for t in query.split() if t.strip()]
    for term in terms:
        like = f"%{term}%"
        q = q.filter(or_(
            Document.filename.ilike(like),
            Document.ocr_text.ilike(like),
            Document.summary.ilike(like),
            Document.tags.cast(String).ilike(like),
            Document.person_first_name.ilike(like),
            Document.person_last_name.ilike(like),
            Document.organization.ilike(like),
        ))
    return {d.id for d in q.with_entities(Document.id).all()}


def _merge_hybrid(sem_ids: list[int], ft_ids: set[int]) -> list[int]:
    """Merge semantic + fulltext results: both-sets first, then semantic-only, then ft-only."""
    seen: set[int] = set()
    result: list[int] = []

    # Tier 1: in both
    for did in sem_ids:
        if did in ft_ids:
            result.append(did)
            seen.add(did)
    # Tier 2: semantic only
    for did in sem_ids:
        if did not in seen:
            result.append(did)
            seen.add(did)
    # Tier 3: fulltext only
    for did in ft_ids:
        if did not in seen:
            result.append(did)

    return result


def _build_response(
    docs: list,
    total: int,
    page: int,
    page_size: int,
    mode: str,
    query: str,
) -> SearchResponse:
    results = [
        SearchResult(
            document=DocumentOut.model_validate(d),
            score=1.0,
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


# ── AI Q&A endpoint ───────────────────────────────────────────────────────────

@router.get("/ask", response_model=AIAnswerResponse)
async def ask_documents(
    query: str = Query(""),
    language: str = Query("en"),
    db: Session = Depends(get_db),
):
    """Answer a free-form question about the user's documents using AI."""
    if not query.strip():
        return AIAnswerResponse(answer="", sources=[], cost=0.0)

    # Find relevant docs: semantic first, fallback to fulltext
    doc_ids = _semantic_ids(query, 12)
    base = db.query(Document).filter(Document.is_deleted == False)

    if doc_ids:
        docs_all = base.filter(Document.id.in_(doc_ids)).all()
        rank = {did: i for i, did in enumerate(doc_ids)}
        docs_all.sort(key=lambda d: rank.get(d.id, 9999))
        docs = docs_all[:10]
    else:
        terms = [t.strip() for t in query.split() if t.strip()]
        q = base
        for term in terms:
            like = f"%{term}%"
            q = q.filter(or_(
                Document.filename.ilike(like),
                Document.ocr_text.ilike(like),
                Document.summary.ilike(like),
                Document.tags.cast(String).ilike(like),
                Document.person_first_name.ilike(like),
                Document.person_last_name.ilike(like),
                Document.organization.ilike(like),
            ))
        docs = q.order_by(Document.added_at.desc()).limit(10).all()

    source_docs = [DocumentOut.model_validate(d) for d in docs]

    # Pick first enabled analysis provider
    provider = (
        db.query(AIProvider)
        .filter(AIProvider.enabled == True, AIProvider.task_type.in_(["analysis", "both"]))
        .order_by(AIProvider.sort_order)
        .first()
    )
    if not provider:
        return AIAnswerResponse(answer="", sources=source_docs, cost=0.0, no_provider=True)

    # Build context from retrieved documents
    context_parts = []
    for i, doc in enumerate(docs, 1):
        parts = [f"[{i}] {doc.filename}"]
        if doc.document_type:
            parts.append(f"Type: {doc.document_type}")
        if doc.document_date:
            parts.append(f"Date: {doc.document_date.strftime('%Y-%m-%d')}")
        name = " ".join(filter(None, [doc.person_first_name, doc.person_last_name]))
        if name:
            parts.append(f"Person: {name}")
        if doc.organization:
            parts.append(f"Organization: {doc.organization}")
        if doc.amount:
            parts.append(f"Amount: {doc.amount} {doc.amount_currency or ''}")
        if doc.tags:
            parts.append(f"Tags: {', '.join(doc.tags)}")
        if doc.summary:
            parts.append(f"Summary: {doc.summary[:600]}")
        context_parts.append("\n".join(parts))

    context = "\n\n---\n\n".join(context_parts)

    lang_names = {"en": "English", "ru": "Russian", "fr": "French"}
    resp_lang = lang_names.get(language, "English")

    system = (
        "You are a personal document assistant helping a user search their scanned document archive. "
        "The documents below were retrieved as most relevant to the user's question. "
        "Answer the question based on these documents. "
        "Reference specific documents using their numbers in brackets like [1] or [2]. "
        "If the answer is not found in the documents, say so honestly. "
        f"Respond in {resp_lang}."
    )
    user_msg = f"Documents:\n\n{context}\n\nQuestion: {query}"

    try:
        from ..services.ai_analysis import run_text
        answer, _, _, cost = await run_text(provider, system, user_msg)
    except Exception as exc:
        answer = str(exc)
        cost = 0.0

    return AIAnswerResponse(answer=answer, sources=source_docs, cost=cost)
