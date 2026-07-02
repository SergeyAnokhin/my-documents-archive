"""
Indexing pipeline: OCR → Thumbnail → AI Vision → AI Analysis → Embedding.

Each step is independent and can be re-run.
Vision only runs when 'enable_ai_vision' = 'true' in AppSettings.
Embedding runs after analysis; falls back silently if chromadb/ST unavailable.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import AppSettings, Document, IndexingLog
from .ocr import extract_text
from .thumbnails import generate_thumbnail
from .ai_analysis import AnalysisResult, analyze_document
from .ai_vision import describe_document

log = logging.getLogger(__name__)


# ── Per-document pipeline ─────────────────────────────────────────────────────

async def index_document(document_id: int, force_full: bool = False) -> None:
    """OCR → Thumbnail → Vision → Analysis → Embedding.

    Steps run depend on the 'auto_process_mode' AppSetting:
      full       — all steps (default)
      ocr_only   — local OCR + thumbnail only; skip Vision + Analysis
      manual     — thumbnail only; skip OCR + Vision + Analysis
                   (leaves ocr_status=pending so batch-OCR tasks can pick it up)

    Pass force_full=True to always run all steps regardless of the setting
    (used by the per-document re-index endpoint).
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return

        if force_full:
            mode = "full"
        else:
            mode_row = db.query(AppSettings).filter(AppSettings.key == "auto_process_mode").first()
            mode = mode_row.value if mode_row else "full"

        is_docx = _is_docx(doc)

        if not is_docx:
            _run_thumbnail(doc, db)

        if mode != "manual":
            if is_docx:
                await _run_docx_extract(doc, db)
            else:
                await _run_ocr(doc, db)

        if mode == "full":
            if not is_docx:
                await _run_vision(doc, db)
            await _run_analysis(doc, db)

        await _run_embedding(doc, db)
        doc.indexed_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        log.error("index_document(%s) crashed: %s", document_id, e)
    finally:
        db.close()


# ── Step 1 — OCR ──────────────────────────────────────────────────────────────

async def _run_ocr(doc: Document, db: Session) -> None:
    if doc.ocr_status == "done":
        return

    doc.ocr_status = "pending"
    db.commit()

    try:
        priority = db.query(AppSettings).filter(AppSettings.key == "ocr_priority").first()
        engines = [e.strip() for e in priority.value.split(",")] if priority else None
        text, engine = await extract_text(doc.filepath, engines=engines)
        doc.ocr_text = text
        doc.ocr_model = engine
        doc.ocr_status = "done"
        _log(db, doc, "ocr", "done", level="trace")
        from .usage import record_usage
        record_usage(
            usage_type="ocr",
            provider_type="worker" if engine == "easyocr" else "local",
            model=engine,
            cost_usd=0.0,
            document_id=doc.id,
        )
    except Exception as e:
        doc.ocr_status = "error"
        doc.ocr_error = str(e)
        _log(db, doc, "ocr", "error", str(e), level="error")
        log.warning("OCR failed for doc %s: %s", doc.id, e)

    db.commit()


# ── Step 1b — Native text extraction (.docx) ─────────────────────────────────

def _is_docx(doc: Document) -> bool:
    return Path(doc.filepath).suffix.lower() == ".docx"


async def _run_docx_extract(doc: Document, db: Session) -> None:
    """Docx equivalent of _run_ocr — no OCR engine involved, text is native."""
    if doc.ocr_status == "done":
        return

    doc.ocr_status = "pending"
    db.commit()

    try:
        from .docx_extract import extract_docx_text
        text = await asyncio.to_thread(extract_docx_text, doc.filepath)
        doc.ocr_text = text
        doc.ocr_model = "native"
        doc.ocr_status = "done"
        doc.vision_status = "skipped"  # no page image exists for docx — Vision never applies
        _log(db, doc, "ocr", "done", "native docx text extraction", level="trace")
    except Exception as e:
        doc.ocr_status = "error"
        doc.ocr_error = str(e)
        _log(db, doc, "ocr", "error", str(e), level="error")
        log.warning("Docx extraction failed for doc %s: %s", doc.id, e)

    db.commit()


# ── Step 2 — Thumbnail ────────────────────────────────────────────────────────

def _run_thumbnail(doc: Document, db: Session) -> None:
    if doc.thumbnail_path:
        return
    try:
        thumb = generate_thumbnail(doc.filepath, doc.id)
        if thumb:
            doc.thumbnail_path = thumb
            db.commit()
    except Exception as e:
        log.warning("Thumbnail failed for doc %s: %s", doc.id, e)


# ── Step 3 — AI Vision ────────────────────────────────────────────────────────

# Vision only sees the document's first page (services/ai_vision.py::load_first_page).
# Its combined vision+analysis JSON is trusted as the source of summary/title/tags
# only when that first page is effectively the only real text we have — otherwise
# a cover/title page would overwrite a much fuller OCR/native-extracted document.
VISION_ANALYSIS_OVERRIDE_MAX_OCR_LEN = 200


async def _run_vision(doc: Document, db: Session) -> None:
    if doc.vision_status == "done":
        return

    # Check AppSettings toggle (default: disabled)
    setting = db.query(AppSettings).filter(AppSettings.key == "enable_ai_vision").first()
    if not setting or setting.value != "true":
        doc.vision_status = "skipped"
        db.commit()
        return

    doc.vision_status = "pending"
    db.commit()

    try:
        result = await describe_document(doc.filepath, db)
        if result is None:
            doc.vision_status = "skipped"
            _log(db, doc, "vision", "skipped", "No vision provider configured", level="debug")
        else:
            text, analysis, cost = result
            doc.vision_description = text
            doc.api_cost_vision = cost
            doc.vision_status = "done"
            has_fuller_text = len((doc.ocr_text or "").strip()) >= VISION_ANALYSIS_OVERRIDE_MAX_OCR_LEN
            if analysis and not has_fuller_text:
                # First page is effectively the only text available — trust
                # the capable model's combined analysis and skip Step 4.
                _apply_analysis_result(doc, analysis, db)
                doc.analysis_status = "done"
                _log(db, doc, "vision", "done",
                     f"with analysis: type={doc.document_type}, lang={doc.language}", level="info")
                _log(db, doc, "analysis", "done",
                     f"via vision: {doc.document_type}, {doc.language}", level="info")
            else:
                # Mistral OCR, unparseable response, or a fuller OCR/native text
                # already exists — Step 4 analyzes the full document instead of
                # relying on vision's first-page-only summary/title/tags.
                _log(db, doc, "vision", "done", level="trace")
    except Exception as e:
        doc.vision_status = "error"
        doc.vision_error = str(e)
        _log(db, doc, "vision", "error", str(e), level="error")
        log.warning("Vision failed for doc %s: %s", doc.id, e)

    db.commit()


# ── Step 4 — AI Analysis ──────────────────────────────────────────────────────

async def _run_analysis(doc: Document, db: Session) -> None:
    if doc.analysis_status == "done":
        return
    if not doc.ocr_text and not doc.vision_description:
        doc.analysis_status = "skipped"
        db.commit()
        return

    doc.analysis_status = "pending"
    db.commit()

    try:
        result = await analyze_document(
            doc.ocr_text or "",
            db,
            vision_description=doc.vision_description,
        )
        if result is None:
            doc.analysis_status = "skipped"
            _log(db, doc, "analysis", "skipped", "No AI provider configured", level="debug")
        else:
            _apply_analysis_result(doc, result, db)
            doc.api_cost_analysis = result.cost_usd
            doc.analysis_status   = "done"
            _log(db, doc, "analysis", "done",
                 f"Type: {result.document_type}, lang: {result.language}", level="info")
    except Exception as e:
        doc.analysis_status = "error"
        doc.analysis_error  = str(e)
        _log(db, doc, "analysis", "error", str(e), level="error")
        log.warning("Analysis failed for doc %s: %s", doc.id, e)

    db.commit()


# ── Step 5 — Embedding ────────────────────────────────────────────────────────

async def _run_embedding(doc: Document, db: Session) -> None:
    """Add/update document embedding in ChromaDB. Skips silently on error."""
    text = " ".join(filter(None, [
        doc.summary or "",
        (doc.ocr_text or "")[:1500],
    ])).strip()
    if not text:
        return
    try:
        from .embeddings import embed_document
        await asyncio.to_thread(embed_document, doc.id, text)
        from .usage import record_usage
        record_usage(
            usage_type="embedding",
            provider_type="local",
            model="sentence-transformers",
            cost_usd=0.0,
            document_id=doc.id,
        )
    except Exception as e:
        log.warning("Embedding failed for doc %s: %s", doc.id, e)


async def embed_document_by_id(document_id: int) -> None:
    """Public wrapper: embed a single document without re-running analysis."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return
        await _run_embedding(doc, db)
        db.commit()
    finally:
        db.close()


# ── Batch processing ──────────────────────────────────────────────────────────

async def index_pending_batch(limit: int = 50) -> dict:
    """Process up to `limit` documents whose ocr_status is 'pending'."""
    db = SessionLocal()
    try:
        pending = (
            db.query(Document)
            .filter(Document.is_deleted == False, Document.ocr_status == "pending")
            .limit(limit)
            .all()
        )
        processed = errors = 0
        for doc in pending:
            try:
                if _is_docx(doc):
                    await _run_docx_extract(doc, db)
                else:
                    await _run_ocr(doc, db)
                    _run_thumbnail(doc, db)
                    await _run_vision(doc, db)
                await _run_analysis(doc, db)
                await _run_embedding(doc, db)
                doc.indexed_at = datetime.utcnow()
                db.commit()
                processed += 1
            except Exception as e:
                errors += 1
                log.error("Batch: doc %s failed: %s", doc.id, e)

        return {"processed": processed, "errors": errors, "total_pending": len(pending)}
    finally:
        db.close()


# ── Re-classify single document ───────────────────────────────────────────────

async def reclassify_document(document_id: int) -> None:
    """Re-run AI Analysis (and re-embed) on an already-OCR'd document. Resets manual classification."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return
        if not doc.ocr_text and not doc.vision_description:
            _log(db, doc, "analysis", "skipped", "No OCR text — run OCR first", level="warning")
            db.commit()
            return
        doc.analysis_status = "pending"
        doc.manually_classified = False
        db.commit()
        await _run_analysis(doc, db)
        await _run_embedding(doc, db)
    except Exception as e:
        log.error("reclassify_document(%s) crashed: %s", document_id, e)
    finally:
        db.close()


async def reclassify_pending_batch(limit: int = 200) -> dict:
    """Re-classify documents that already have a summary — one LLM call per doc (type only).

    Does NOT regenerate the summary, tags, or any other fields.
    Documents without a summary are skipped and counted in the log.
    """
    db = SessionLocal()
    try:
        skipped_no_summary = (
            db.query(Document)
            .filter(
                Document.is_deleted == False,
                or_(Document.summary.is_(None), Document.summary == ""),
            )
            .count()
        )
        if skipped_no_summary:
            log.info("reclassify_all: skipping %d document(s) with no summary", skipped_no_summary)

        docs = (
            db.query(Document)
            .filter(
                Document.is_deleted == False,
                Document.summary.isnot(None),
                Document.summary != "",
            )
            .limit(limit)
            .all()
        )

        processed = errors = 0
        for doc in docs:
            try:
                new_type = await _classify_from_summary(doc, db)
                if new_type:
                    _apply_type_only(doc, new_type)
                    db.commit()
                    processed += 1
            except Exception as e:
                errors += 1
                log.error("reclassify_pending_batch: doc %s failed: %s", doc.id, e)

        return {"processed": processed, "errors": errors, "skipped_no_summary": skipped_no_summary}
    finally:
        db.close()


async def _classify_from_summary(doc: Document, db: Session) -> str | None:
    """One LLM call: assign document_type from the existing summary. Returns type slug or None."""
    from .ai_analysis import _get_providers, run_text
    from .ai_common import DOCUMENT_TYPES_BLOCK, strip_code_fences
    import json

    providers = _get_providers(db)
    if not providers:
        return None

    user_msg = (
        f"Document summary:\n{doc.summary}\n\n"
        "Choose the most appropriate document type from the list below, "
        "or use 'unclassified' if nothing fits.\n\n"
        f"{DOCUMENT_TYPES_BLOCK}\n\n"
        'Reply with JSON only: {"type": "slug_name"}'
    )

    try:
        text, _, _, _ = await run_text(providers[0], "You are a document type classifier.", user_msg)
        data = json.loads(strip_code_fences(text))
        return data.get("type", "unclassified")
    except Exception as e:
        log.warning("_classify_from_summary doc %s: %s", doc.id, e)
        return None


def _apply_type_only(doc: Document, new_type: str) -> None:
    """Set document_type only. Preserves old type in tags if it was meaningful and changed."""
    old_type = doc.document_type
    if old_type and old_type not in ("unclassified", "other") and old_type != new_type:
        existing = list(doc.tags or [])
        if old_type not in existing:
            existing.append(old_type)
        doc.tags = existing
    doc.document_type = new_type
    doc.classification_source = "auto"


async def reclassify_unclassified_batch(limit: int = 200) -> dict:
    """Re-run AI Analysis on docs still typed as unclassified/other and not manually set."""
    db = SessionLocal()
    try:
        candidates = (
            db.query(Document)
            .filter(
                Document.is_deleted == False,
                Document.manually_classified == False,
                Document.document_type.in_(["unclassified", "other", None]),
                (Document.ocr_text != None) | (Document.vision_description != None),
            )
            .limit(limit)
            .all()
        )
        processed = errors = 0
        for doc in candidates:
            try:
                doc.analysis_status = "pending"
                db.commit()
                await _run_analysis(doc, db)
                await _run_embedding(doc, db)
                processed += 1
            except Exception as e:
                errors += 1
                log.error("reclassify_unclassified_batch: doc %s failed: %s", doc.id, e)
        return {"processed": processed, "errors": errors, "total_candidates": len(candidates)}
    finally:
        db.close()


def _is_unclassified(doc: Document) -> bool:
    return doc.document_type in (None, "unclassified", "other")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_analysis_result(doc: Document, result: AnalysisResult, db: Session) -> None:
    """Write AnalysisResult metadata onto a Document.

    Shared by Step 3 (vision-as-analysis) and Step 4 (text analysis). Does NOT
    touch status or api_cost columns — the caller owns those, since cost lands in
    `api_cost_vision` vs `api_cost_analysis` depending on which step produced it.
    """
    old_type = doc.document_type
    new_type = result.document_type

    doc.summary                   = result.summary
    doc.title                     = result.title or None
    doc.document_type             = new_type
    doc.classification_confidence = result.document_type_confidence
    doc.classification_source     = "auto"

    # Merge LLM tags with old type preserved (old type → tag when reclassifying)
    new_tags = list(result.tags or [])
    if old_type and old_type not in ("unclassified", "other") and old_type != new_type:
        if old_type not in new_tags:
            new_tags.append(old_type)
    doc.tags               = new_tags
    doc.language           = result.language
    doc.organization       = result.organization
    doc.amount             = result.amount
    doc.amount_currency    = result.amount_currency
    doc.person_first_name  = result.person_first_name
    doc.person_last_name   = result.person_last_name
    if result.document_date:
        try:
            doc.document_date = datetime.strptime(result.document_date, "%Y-%m-%d")
        except ValueError:
            pass
    if doc.source == "upload" and result.short_title:
        _rename_uploaded_file(doc, result.short_title, db)


def _rename_uploaded_file(doc: Document, short_title: str, db: Session) -> None:
    """Rename an uploaded file to its AI-generated short title, preserving extension."""
    old_path = Path(doc.filepath)
    safe = re.sub(r"[^a-z0-9_]", "_", short_title.lower().strip())
    safe = re.sub(r"_+", "_", safe).strip("_")[:40]
    if not safe:
        return
    new_name = f"{safe}{old_path.suffix.lower()}"
    new_path = old_path.parent / new_name
    counter = 1
    while new_path.exists() and new_path != old_path:
        new_path = old_path.parent / f"{safe}_{counter}{old_path.suffix.lower()}"
        counter += 1
    if new_path == old_path:
        return
    try:
        old_path.rename(new_path)
        doc.filepath = str(new_path)
        doc.filename = new_path.name
        db.commit()
    except OSError as e:
        log.warning("Could not rename %s → %s: %s", old_path.name, new_path.name, e)


def _log(db: Session, doc: Document, step: str, status: str, message: str = "", level: str = "info") -> None:
    entry = IndexingLog(
        document_id=doc.id,
        filename=doc.filename,
        step=step,
        status=status,
        message=message,
        level=level,
    )
    db.add(entry)
    db.commit()
