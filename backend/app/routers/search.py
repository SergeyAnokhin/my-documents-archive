from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, extract, func, String
from typing import Optional
import logging
import re
import time

log = logging.getLogger(__name__)

from ..database import get_db
from ..models import Document, AIProvider, IndexingLog
from ..schemas import (
    SearchResponse, SearchResult, DocumentOut, AIAnswerResponse,
    AskDebug, AskDebugDoc,
)

router = APIRouter(prefix="/api/search", tags=["search"])


def _parse_query(query: str) -> tuple[list[str], list[str]]:
    """Split query into exact phrases (quoted) and individual words.

    Example: `договор "Иванов Иван" 2024` → (['Иванов Иван'], ['договор', '2024'])
    """
    phrases = re.findall(r'"([^"]+)"', query)
    remainder = re.sub(r'"[^"]+"', '', query)
    words = [w.strip() for w in remainder.split() if w.strip()]
    return phrases, words


def _apply_text_filter(q, phrases: list[str], words: list[str]):
    """Add LIKE filters for all phrases and words to a SQLAlchemy query."""
    COLS = lambda like: or_(
        Document.filename.ilike(like),
        Document.ocr_text.ilike(like),
        Document.summary.ilike(like),
        Document.document_type.ilike(like),
        Document.tags.cast(String).ilike(like),
        Document.person_first_name.ilike(like),
        Document.person_last_name.ilike(like),
        Document.organization.ilike(like),
    )
    for phrase in phrases:
        q = q.filter(COLS(f"%{phrase}%"))
    for word in words:
        q = q.filter(COLS(f"%{word}%"))
    return q


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _semantic_ids(query: str, n: int) -> list[int]:
    try:
        from ..services.embeddings import search_similar
        return search_similar(query, n_results=n)
    except Exception:
        return []


def _semantic_scored(query: str, n: int) -> list[tuple[int, float]]:
    try:
        from ..services.embeddings import search_similar_scored
        return search_similar_scored(query, n_results=n)
    except Exception:
        return []


def _fulltext_ids(base_query, query: str) -> set[int]:
    phrases, words = _parse_query(query)
    q = _apply_text_filter(base_query, phrases, words)
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


# ── Transliteration helpers ────────────────────────────────────────────────────

_CYR_TO_LAT: dict[str, str] = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

# Common first-name Latin→Cyrillic map for cross-script name matching
_LAT_NAME_TO_CYR: dict[str, str] = {
    'sergey': 'сергей', 'sergei': 'сергей', 'serge': 'сергей',
    'alexey': 'алексей', 'aleksey': 'алексей', 'alexei': 'алексей',
    'ivan': 'иван', 'anna': 'анна', 'igor': 'игорь', 'olga': 'ольга',
    'andrey': 'андрей', 'andrei': 'андрей',
    'natasha': 'наташа', 'natalia': 'наталья', 'natalya': 'наталья',
    'mikhail': 'михаил', 'michael': 'михаил',
    'nikolay': 'николай', 'nikolai': 'николай', 'nicolas': 'николай',
    'vladimir': 'владимир',
    'dmitry': 'дмитрий', 'dmitri': 'дмитрий', 'dmitriy': 'дмитрий',
    'maxim': 'максим', 'artem': 'артем', 'denis': 'денис',
    'alexander': 'александр', 'alexandre': 'александр',
}


def _transliterate_cyr_to_lat(word: str) -> str:
    return ''.join(_CYR_TO_LAT.get(c, c) for c in word.lower())


def _expand_fulltext_query(query: str) -> list[str]:
    """Return [original, transliterated-variant] for cross-script name matching."""
    variants = [query]
    words = query.split()
    translated: list[str] = []
    for word in words:
        w = word.lower()
        if any(c in _CYR_TO_LAT for c in w):
            translated.append(_transliterate_cyr_to_lat(w))
        elif w in _LAT_NAME_TO_CYR:
            translated.append(_LAT_NAME_TO_CYR[w])
        else:
            translated.append(w)
    translit_query = ' '.join(translated)
    if translit_query.lower() != query.lower():
        variants.append(translit_query)
    return variants


@router.get("/embedded-ids")
def get_embedded_ids():
    """Return the set of document IDs that have embeddings in ChromaDB."""
    from ..services.embeddings import embedded_ids
    return {"ids": sorted(embedded_ids())}


# ── Depth configuration ────────────────────────────────────────────────────────
# Controls how many docs are retrieved, sent to LLM, and how much OCR text per doc.

_DEPTH_CFG = {
    1: {"n_retrieve": 6,  "n_send": 4,  "ocr_chars": 0},     # Fast: summary only
    2: {"n_retrieve": 12, "n_send": 6,  "ocr_chars": 600},    # Normal: default
    3: {"n_retrieve": 20, "n_send": 12, "ocr_chars": 1500},   # Deep: full OCR
}


# ── AI Q&A endpoint ───────────────────────────────────────────────────────────

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
    if not query.strip():
        return AIAnswerResponse(answer="", sources=[], cost=0.0)

    t0 = time.perf_counter()
    cfg = _DEPTH_CFG.get(depth, _DEPTH_CFG[2])
    log.info("🔍 [ask] start  query=%r  depth=%d  n_retrieve=%d  n_send=%d",
             query[:80], depth, cfg["n_retrieve"], cfg["n_send"])

    base = db.query(Document).filter(Document.is_deleted == False)
    if year:
        date_col = func.coalesce(Document.document_date, Document.added_at)
        base = base.filter(extract("year", date_col) == year)
    if filter_language:
        base = base.filter(Document.language == filter_language)

    # In debug mode score the *whole* embedded collection so the modal can show
    # exactly where every document ranked (not just the ones that survived the cut).
    from ..services.embeddings import collection_count
    embedded_count = collection_count()
    sem_n = max(embedded_count, cfg["n_retrieve"] * 2) if debug else cfg["n_retrieve"] * 2

    # ── Hybrid retrieval: semantic + fulltext always merged ────────────────
    t1 = time.perf_counter()
    sem_scored = _semantic_scored(query, sem_n)
    sem_ids   = [sid for sid, _ in sem_scored]
    sem_dist  = {sid: dist for sid, dist in sem_scored}
    semantic_ms = (time.perf_counter() - t1) * 1000
    log.debug("🧠 [ask] step=semantic  ids=%d  ms=%.0f", len(sem_ids), semantic_ms)

    t2 = time.perf_counter()
    query_variants = _expand_fulltext_query(query)
    log.debug("📄 [ask] step=fulltext  variants=%s", query_variants)
    ft_ids: set[int] = set()
    for variant in query_variants:
        ft_ids |= _fulltext_ids(base, variant)
    fulltext_ms = (time.perf_counter() - t2) * 1000
    log.debug("📄 [ask] step=fulltext  ids=%d  variants=%d  ms=%.0f",
              len(ft_ids), len(query_variants), fulltext_ms)

    merged = _merge_hybrid(sem_ids, ft_ids)
    log.debug("🔀 [ask] step=merge  total=%d  selected=%d",
              len(merged), min(len(merged), cfg["n_retrieve"]))

    if merged:
        docs_all = base.filter(Document.id.in_(merged[:cfg["n_retrieve"]])).all()
        rank = {did: i for i, did in enumerate(merged)}
        docs_all.sort(key=lambda d: rank.get(d.id, 9999))
    else:
        docs_all = base.order_by(Document.added_at.desc()).limit(cfg["n_retrieve"]).all()

    docs = docs_all[:cfg["n_send"]]
    log.debug("📂 [ask] selected docs (%d): %s", len(docs),
              [(d.id, d.filename[:40]) for d in docs])

    # ── Retrieval report (INFO) ────────────────────────────────────────────
    # The single most useful diagnostic: for the whole candidate pool, show each
    # doc's similarity score, where it came from, and whether it survived the
    # n_retrieve / n_send cuts. This is what reveals *why* a relevant document
    # (e.g. a visa) was dropped before ever reaching the LLM.
    _log_retrieval(base, query_variants, merged, sem_dist, ft_ids,
                   sent_ids={d.id for d in docs},
                   retrieved_ids={d.id for d in docs_all},
                   cfg=cfg)

    # ── Debug trace (advanced mode) ────────────────────────────────────────
    dbg: Optional[AskDebug] = None
    if debug:
        dbg = _build_ask_debug(
            base, query, query_variants, depth, cfg,
            sem_scored, ft_ids, docs_all, docs,
            total_docs=base.count(),
            embedded_count=embedded_count,
            fallback_newest=(not merged),
            semantic_ms=semantic_ms,
            fulltext_ms=fulltext_ms,
        )

    source_docs = [DocumentOut.model_validate(d) for d in docs]

    # ── Provider ───────────────────────────────────────────────────────────
    provider = (
        db.query(AIProvider)
        .filter(AIProvider.enabled == True, AIProvider.task_type.in_(["analysis", "both"]))
        .order_by(AIProvider.sort_order)
        .first()
    )
    if not provider:
        return AIAnswerResponse(answer="", sources=source_docs, cost=0.0, no_provider=True,
                                docs_sent=len(docs), depth=depth, debug=dbg)

    # ── Context assembly ───────────────────────────────────────────────────
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
        ocr_sent = 0
        if cfg["ocr_chars"] > 0 and doc.ocr_text:
            ocr_sent = min(len(doc.ocr_text), cfg["ocr_chars"])
            parts.append(f"Text: {doc.ocr_text[:cfg['ocr_chars']]}")
        context_parts.append("\n".join(parts))
        log.debug("[ask] ctx doc[%d] id=%d filename=%r summary=%s ocr_sent=%d",
                  i, doc.id, doc.filename[:40], bool(doc.summary), ocr_sent)

    context = "\n\n---\n\n".join(context_parts)
    log.debug("📋 [ask] step=context  docs=%d  chars=%d  provider=%r  model=%r",
              len(docs), len(context), provider.name, provider.model)

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

    t4 = time.perf_counter()
    try:
        from ..services.ai_analysis import run_text
        answer, tokens_in, tokens_out, cost = await run_text(provider, system, user_msg)
        log.debug("✨ [ask] step=llm  ms=%.0f  tokens=%d/%d  cost=$%.5f",
                  (time.perf_counter() - t4) * 1000, tokens_in, tokens_out, cost)
    except Exception as exc:
        answer = str(exc)
        tokens_in = tokens_out = 0
        cost = 0.0
        log.warning("❌ [ask] LLM call failed: %s", exc)
    llm_ms = (time.perf_counter() - t4) * 1000

    model_name = provider.model or provider.name
    total_ms = (time.perf_counter() - t0) * 1000
    log.info("✅ [ask] done  total_ms=%.0f  provider=%s  type=%s  model=%s  depth=%d  docs_sent=%d  tokens=%d/%d  cost=$%.5f  answer_chars=%d",
             total_ms, provider.name, provider.provider_type, model_name, depth, len(docs),
             tokens_in, tokens_out, cost, len(answer or ""))

    if dbg is not None:
        dbg.context_chars = len(context)
        dbg.system_prompt = system
        dbg.user_prompt = user_msg
        dbg.llm_ms = llm_ms
        dbg.total_ms = total_ms
        dbg.provider_name = provider.name
        dbg.model_name = model_name
    _log_ask(db, query, len(docs), depth, cost, tokens_in, tokens_out, model_name)
    from ..services.usage import record_usage
    record_usage(
        usage_type="qa",
        provider_type=provider.provider_type,
        provider_name=provider.name,
        model=model_name,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
    )

    return AIAnswerResponse(
        answer=answer,
        sources=source_docs,
        cost=cost,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model_name=model_name,
        docs_sent=len(docs),
        depth=depth,
        debug=dbg,
    )


def _build_ask_debug(
    base_query,
    query: str,
    query_variants: list[str],
    depth: int,
    cfg: dict,
    sem_scored: list[tuple[int, float]],
    ft_ids: set[int],
    docs_all: list,
    docs: list,
    total_docs: int,
    embedded_count: int,
    fallback_newest: bool,
    semantic_ms: float,
    fulltext_ms: float,
) -> AskDebug:
    """Assemble the per-request retrieval trace returned to the debug modal.

    `semantic` lists every embedded document scored against the query (closest
    first) with its similarity and selection flags — this is what shows *where*
    a relevant document ranked and which cut (n_retrieve / n_send) dropped it.
    """
    sent_ids      = {d.id for d in docs}
    retrieved_ids = {d.id for d in docs_all}
    sem_ids       = [sid for sid, _ in sem_scored]

    rows = (
        base_query.filter(Document.id.in_(set(sem_ids)))
        .with_entities(Document.id, Document.filename, Document.document_type)
        .all()
        if sem_ids else []
    )
    meta = {r[0]: (r[1], r[2]) for r in rows}

    semantic = []
    for rank, (sid, dist) in enumerate(sem_scored, 1):
        fn, dt = meta.get(sid, ("?", None))
        semantic.append(AskDebugDoc(
            rank=rank,
            doc_id=sid,
            filename=fn,
            document_type=dt,
            similarity=(1 - dist) if dist is not None else None,
            distance=dist,
            in_fulltext=sid in ft_ids,
            retrieved=sid in retrieved_ids,
            sent=sid in sent_ids,
        ))

    return AskDebug(
        query=query,
        query_variants=query_variants,
        depth=depth,
        n_retrieve=cfg["n_retrieve"],
        n_send=cfg["n_send"],
        ocr_chars=cfg["ocr_chars"],
        embedded_count=embedded_count,
        total_docs=total_docs,
        fulltext_count=len(ft_ids),
        fulltext_ids=sorted(ft_ids),
        semantic=semantic,
        retrieved_ids=[d.id for d in docs_all],
        sent_ids=[d.id for d in docs],
        fallback_newest=fallback_newest,
        semantic_ms=semantic_ms,
        fulltext_ms=fulltext_ms,
    )


def _log_retrieval(
    base_query,
    query_variants: list[str],
    merged: list[int],
    sem_dist: dict[int, float],
    ft_ids: set[int],
    sent_ids: set[int],
    retrieved_ids: set[int],
    cfg: dict,
) -> None:
    """Emit a human-readable INFO table of the ask retrieval pool.

    One line per candidate document, ordered by merge rank, showing:
      status  — SENT→LLM (in context) · retrieved (in pool, cut before LLM) · dropped (cut from pool)
      sim     — cosine similarity (1 - distance); higher = closer. "ft-only" = no embedding hit.
      src     — sem · ft · sem+ft  (which retriever surfaced it)
    The cut points are n_retrieve (pool→retrieved) and n_send (retrieved→LLM).
    """
    if not merged:
        log.info("🔎 [ask] retrieval  pool=0  (no semantic or fulltext matches; "
                 "answering from newest docs)  variants=%s", query_variants)
        return

    # filename lookup for the whole candidate pool, one query
    fname = dict(
        base_query.filter(Document.id.in_(set(merged)))
        .with_entities(Document.id, Document.filename)
        .all()
    )

    lines = [
        "🔎 [ask] retrieval  semantic=%d  fulltext=%d  variants=%s  → retrieve top %d, send top %d"
        % (len(sem_dist), len(ft_ids), query_variants, cfg["n_retrieve"], cfg["n_send"]),
    ]
    for rank, did in enumerate(merged, 1):
        if did in sent_ids:
            status = "SENT→LLM"
        elif did in retrieved_ids:
            status = "retrieved"
        else:
            status = "dropped"
        dist = sem_dist.get(did)
        sim = f"{1 - dist:5.3f}" if dist is not None else "ft-only"
        src = "sem+ft" if (did in sem_dist and did in ft_ids) else ("sem" if did in sem_dist else "ft")
        lines.append(
            f"   #{rank:<2} {status:<9} sim={sim:<7} src={src:<6} id={did:<5} {fname.get(did, '?')[:50]}"
        )
    log.info("\n".join(lines))


def _log_ask(
    db, query: str, n_docs: int, depth: int,
    cost: float, tokens_in: int, tokens_out: int, model_name: str,
) -> None:
    """Write an ask-pipeline summary to the admin log."""
    try:
        msg = (
            f"query={query[:80]!r}  depth={depth}  docs={n_docs}  "
            f"model={model_name}  tokens={tokens_in}in/{tokens_out}out  "
            f"cost=${cost:.5f}"
        )
        entry = IndexingLog(step="ask", status="done", message=msg, api_cost=cost)
        db.add(entry)
        db.commit()
    except Exception:
        pass
