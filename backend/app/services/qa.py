"""AI Q&A (/ask) pipeline: hybrid retrieval → context assembly → LLM answer.

Split out of routers/search.py. This module owns everything between the raw
query and the AIAnswerResponse: depth config, retrieval + merge, the context
block and prompts sent to the (paid) LLM provider, usage recording, and the
debug/logging trace. The router stays a thin endpoint wrapper.
"""
import logging
import time
from typing import Optional

from sqlalchemy import extract, func

from ..models import Document, AIProvider, IndexingLog
from ..schemas import AIAnswerResponse, AskDebug, AskDebugDoc, DocumentOut
from .search_query import _expand_fulltext_query, _fulltext_ids, _merge_hybrid, _semantic_scored

log = logging.getLogger(__name__)


# ── Depth configuration ────────────────────────────────────────────────────────
# Controls how many docs are retrieved, sent to LLM, and how much OCR text per doc.

_DEPTH_CFG = {
    1: {"n_retrieve": 6,  "n_send": 4,  "ocr_chars": 0},     # Fast: summary only
    2: {"n_retrieve": 12, "n_send": 6,  "ocr_chars": 600},    # Normal: default
    3: {"n_retrieve": 20, "n_send": 12, "ocr_chars": 1500},   # Deep: full OCR
}


def build_context(docs: list, ocr_chars: int) -> str:
    """Assemble the numbered document-context block sent to the LLM.

    One `[i]` section per document with its metadata fields; OCR text is
    appended only when `ocr_chars > 0`, truncated to that many characters.
    """
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
        if ocr_chars > 0 and doc.ocr_text:
            ocr_sent = min(len(doc.ocr_text), ocr_chars)
            parts.append(f"Text: {doc.ocr_text[:ocr_chars]}")
        context_parts.append("\n".join(parts))
        log.debug("[ask] ctx doc[%d] id=%d filename=%r summary=%s ocr_sent=%d",
                  i, doc.id, doc.filename[:40], bool(doc.summary), ocr_sent)
    return "\n\n---\n\n".join(context_parts)


def build_prompts(context: str, query: str, language: str) -> tuple[str, str]:
    """Build the (system, user) prompt pair for the QA LLM call."""
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
    return system, user_msg


async def answer_question(
    db,
    query: str,
    language: str = "en",
    year: Optional[int] = None,
    filter_language: Optional[str] = None,
    depth: int = 2,
    debug: bool = False,
) -> AIAnswerResponse:
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
    from .embeddings import collection_count
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
    source_similarities = [
        (1.0 - sem_dist[d.id]) if d.id in sem_dist else None
        for d in docs
    ]

    # ── Provider ───────────────────────────────────────────────────────────
    provider = (
        db.query(AIProvider)
        .filter(AIProvider.enabled == True, AIProvider.task_type.in_(["analysis", "both"]))
        .order_by(AIProvider.sort_order)
        .first()
    )
    if not provider:
        return AIAnswerResponse(answer="", sources=source_docs, source_similarities=source_similarities,
                                cost=0.0, no_provider=True, docs_sent=len(docs), depth=depth, debug=dbg)

    # ── Context assembly ───────────────────────────────────────────────────
    context = build_context(docs, cfg["ocr_chars"])
    log.debug("📋 [ask] step=context  docs=%d  chars=%d  provider=%r  model=%r",
              len(docs), len(context), provider.name, provider.model)

    system, user_msg = build_prompts(context, query, language)

    t4 = time.perf_counter()
    try:
        from .ai_analysis import run_text
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
    from .usage import record_usage
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
        source_similarities=source_similarities,
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
