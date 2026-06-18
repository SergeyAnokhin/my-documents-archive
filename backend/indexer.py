"""Background indexing pipeline.

Four-step process (independent, configurable):
  Step 1 — OCR: extract text (Tesseract)
  Step 2 — AI Vision: visual description of the image (multimodal LLM)
  Step 3 — AI Analysis: tags, summary, type from combined text + vision
  + Semantic embeddings for meaning-based search

Batch mode: process N documents with progress tracking.
Retry logic: auto-retry failed steps up to max_retries times."""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import get_ai_config
from backend.database import SessionLocal
from backend.models import Document, IndexingStatus
from backend.ocr import process_document
from backend.ai_analysis import analyze_document
from backend.vision import analyze_image
from backend.embeddings import index_embedding

logger = logging.getLogger(__name__)

# ── Retry config ─────────────────────────────────────────

DEFAULT_MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5  # Wait between retries


# ── Batch progress tracking ──────────────────────────────

_batch_jobs: dict[str, dict] = {}  # job_id → {total, processed, errors, status, started_at}


def get_batch_status(job_id: str) -> Optional[dict]:
    """Get status of a batch indexing job."""
    return _batch_jobs.get(job_id)


# ── Single document indexing ─────────────────────────────

def index_document(
    doc_id: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """Run full indexing pipeline on a single document.

    Returns dict with per-step status: {ocr, vision, analysis, embeddings}.
    Each status is one of: 'done', 'skipped', 'error', 'pending'.
    """
    db = SessionLocal()
    result = {"ocr": "pending", "vision": "pending", "analysis": "pending", "embeddings": "pending"}

    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            result["error"] = "not_found"
            return result

        file_path = Path(doc.file_path)
        if not file_path.exists():
            doc.ocr_status = IndexingStatus.error
            db.commit()
            result["error"] = "file_missing"
            return result

        ai_config = get_ai_config()
        changed = False

        # ── Step 1: OCR (with retry) ─────────────────────
        if doc.ocr_status in (IndexingStatus.pending, IndexingStatus.error):
            ocr_text = _retry_operation(
                lambda: process_document(file_path),
                max_retries=max_retries,
                operation_name=f"OCR:{doc_id}",
            )
            if ocr_text is not None:
                doc.ocr_text = ocr_text
                doc.ocr_status = IndexingStatus.done
                result["ocr"] = "done"
            elif ocr_text == "":
                doc.ocr_text = ""
                doc.ocr_status = IndexingStatus.done
                result["ocr"] = "done"
            else:
                doc.ocr_status = IndexingStatus.error
                result["ocr"] = "error"
            changed = True
        elif doc.ocr_status == IndexingStatus.done:
            result["ocr"] = "done"
        elif doc.ocr_status == IndexingStatus.skipped:
            result["ocr"] = "skipped"

        db.commit()

        # ── Step 2: AI Vision (with retry) ────────────────
        vision_enabled = ai_config.get("vision_enabled", False)
        if vision_enabled and doc.vision_status in (IndexingStatus.pending, IndexingStatus.error):
            description = _retry_operation(
                lambda: analyze_image(file_path, doc.original_filename),
                max_retries=max_retries,
                operation_name=f"Vision:{doc_id}",
            )
            if description:
                doc.vision_description = description
                doc.vision_status = IndexingStatus.done
                result["vision"] = "done"
            elif description == "":
                doc.vision_status = IndexingStatus.skipped
                result["vision"] = "skipped"
            else:
                doc.vision_status = IndexingStatus.error
                result["vision"] = "error"
            changed = True
        elif doc.vision_status == IndexingStatus.done:
            result["vision"] = "done"
        elif doc.vision_status == IndexingStatus.skipped:
            result["vision"] = "skipped"

        db.commit()

        # ── Step 3: AI Analysis (with retry) ──────────────
        if ai_config.get("analysis_enabled", True) and doc.analysis_status in (
            IndexingStatus.pending, IndexingStatus.error
        ):
            input_text = doc.ocr_text or ""
            if doc.vision_description:
                input_text = f"{input_text}\n\n[Visual description]: {doc.vision_description}"

            if input_text.strip():
                analysis_result = _retry_operation(
                    lambda: analyze_document(input_text, doc.original_filename),
                    max_retries=max_retries,
                    operation_name=f"Analysis:{doc_id}",
                )
                if analysis_result:
                    doc.summary = analysis_result.get("summary", "")
                    doc.tags = analysis_result.get("tags", [])
                    doc.doc_type = analysis_result.get("doc_type", "")
                    doc.doc_language = analysis_result.get("language", "")
                    if analysis_result.get("doc_date"):
                        try:
                            doc.doc_date = datetime.strptime(
                                analysis_result["doc_date"], "%Y-%m-%d"
                            )
                        except (ValueError, TypeError):
                            pass
                    doc.analysis_status = IndexingStatus.done
                    result["analysis"] = "done"
                else:
                    doc.analysis_status = IndexingStatus.error
                    result["analysis"] = "error"
            else:
                doc.analysis_status = IndexingStatus.skipped
                result["analysis"] = "skipped"
            changed = True
        elif doc.analysis_status == IndexingStatus.done:
            result["analysis"] = "done"
        elif doc.analysis_status == IndexingStatus.skipped:
            result["analysis"] = "skipped"

        if changed:
            db.commit()

        # ── Embeddings ──────────────────────────────────
        if doc.ocr_text or doc.summary:
            try:
                embed_text = f"{doc.summary}\n{doc.ocr_text[:2000]}"
                index_embedding(doc.id, embed_text)
                result["embeddings"] = "done"
            except Exception as e:
                logger.debug("Embeddings index skipped for %s: %s", doc_id, e)
                result["embeddings"] = "error"

        return result

    except Exception as e:
        logger.error("Indexing failed for %s: %s", doc_id, e)
        result["error"] = str(e)
        return result
    finally:
        db.close()


# ── Batch indexing ───────────────────────────────────────

def index_batch(
    limit: int = 50,
    job_id: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """Index up to `limit` pending documents. Returns progress summary.

    Also handles errored documents with remaining retries."""
    if not job_id:
        job_id = f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    db = SessionLocal()
    try:
        # Find pending AND errored documents (for retry)
        docs = (
            db.query(Document)
            .filter(
                (Document.ocr_status == IndexingStatus.pending)
                | (Document.ocr_status == IndexingStatus.error)
                | (Document.vision_status == IndexingStatus.pending)
                | (Document.vision_status == IndexingStatus.error)
                | (Document.analysis_status == IndexingStatus.pending)
                | (Document.analysis_status == IndexingStatus.error)
            )
            .limit(limit)
            .all()
        )

        total = len(docs)
        _batch_jobs[job_id] = {
            "total": total,
            "processed": 0,
            "completed": 0,
            "errors": 0,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "doc_ids": [d.id for d in docs],
        }

        for doc in docs:
            result = index_document(doc.id, max_retries=max_retries)
            _batch_jobs[job_id]["processed"] += 1

            # Check overall result
            has_error = any(
                v == "error" for k, v in result.items() if k in ("ocr", "vision", "analysis")
            )
            if has_error:
                _batch_jobs[job_id]["errors"] += 1
            else:
                _batch_jobs[job_id]["completed"] += 1

        _batch_jobs[job_id]["status"] = "done"
        _batch_jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

        return {
            "job_id": job_id,
            "total": total,
            "completed": _batch_jobs[job_id]["completed"],
            "errors": _batch_jobs[job_id]["errors"],
        }

    finally:
        db.close()


def index_next_batch(limit: int = 10) -> int:
    """Process the next N pending documents (simple mode — no progress tracking)."""
    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                (Document.ocr_status == IndexingStatus.pending)
                | (Document.vision_status == IndexingStatus.pending)
                | (Document.analysis_status == IndexingStatus.pending)
            )
            .limit(limit)
            .all()
        )
        for doc in docs:
            index_document(doc.id)
        return len(docs)
    finally:
        db.close()


# ── Retry helper ─────────────────────────────────────────

def _retry_operation(fn, max_retries: int = 3, operation_name: str = "op"):
    """Call fn up to max_retries times. Returns fn() result on success, None on all failures."""
    for attempt in range(1, max_retries + 1):
        try:
            result = fn()
            if attempt > 1:
                logger.info("%s succeeded on attempt %d", operation_name, attempt)
            return result
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    "%s attempt %d/%d failed: %s. Retrying in %ds...",
                    operation_name, attempt, max_retries, e, RETRY_DELAY_SECONDS,
                )
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                logger.error(
                    "%s failed after %d attempts: %s",
                    operation_name, max_retries, e,
                )
                return None
    return None
