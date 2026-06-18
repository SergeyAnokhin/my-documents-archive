"""Background indexing pipeline.

Three-step process (independent, configurable):
  Step 1 — OCR: extract text (Tesseract)
  Step 2 — AI Vision: visual description of the image (multimodal LLM)
  Step 3 — AI Analysis: tags, summary, type from combined text + vision
  + Semantic embeddings for meaning-based search
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import get_ai_config
from backend.database import SessionLocal
from backend.models import Document, IndexingStatus
from backend.ocr import process_document
from backend.ai_analysis import analyze_document
from backend.vision import analyze_image
from backend.embeddings import index_embedding

logger = logging.getLogger(__name__)


def index_document(doc_id: str):
    """Run full indexing pipeline on a single document."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return

        file_path = Path(doc.file_path)
        if not file_path.exists():
            doc.ocr_status = IndexingStatus.error
            db.commit()
            return

        ai_config = get_ai_config()
        changed = False

        # ── Step 1: OCR ─────────────────────────────────
        if doc.ocr_status == IndexingStatus.pending:
            ocr_text = process_document(file_path)
            doc.ocr_text = ocr_text or ""
            doc.ocr_status = IndexingStatus.done
            changed = True
        db.commit()

        # ── Step 2: AI Vision ───────────────────────────
        vision_enabled = ai_config.get("vision_enabled", False)
        if vision_enabled and doc.vision_status == IndexingStatus.pending:
            try:
                description = analyze_image(file_path, doc.original_filename)
                if description:
                    doc.vision_description = description
                    doc.vision_status = IndexingStatus.done
                else:
                    doc.vision_status = IndexingStatus.skipped
                changed = True
            except Exception as e:
                logger.warning("Vision failed for %s: %s", doc_id, e)
                doc.vision_status = IndexingStatus.error
                changed = True
        db.commit()

        # ── Step 3: AI Analysis ─────────────────────────
        if ai_config.get("analysis_enabled", True) and doc.analysis_status == IndexingStatus.pending:
            # Combine OCR + Vision for best input
            input_text = doc.ocr_text or ""
            if doc.vision_description:
                input_text = f"{input_text}\n\n[Visual description]: {doc.vision_description}"

            if input_text.strip():
                try:
                    result = analyze_document(input_text, doc.original_filename)
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
                    changed = True
                except Exception as e:
                    logger.warning("AI analysis failed for %s: %s", doc_id, e)
                    doc.analysis_status = IndexingStatus.error
                    changed = True
            else:
                doc.analysis_status = IndexingStatus.skipped
                changed = True

        if changed:
            db.commit()

        # ── Embeddings ──────────────────────────────────
        if doc.ocr_text or doc.summary:
            try:
                embed_text = f"{doc.summary}\n{doc.ocr_text[:2000]}"
                index_embedding(doc.id, embed_text)
            except Exception as e:
                logger.debug("Embeddings index skipped for %s: %s", doc_id, e)

    except Exception as e:
        logger.error("Indexing failed for %s: %s", doc_id, e)
    finally:
        db.close()


def index_next_batch(limit: int = 10):
    """Process the next N pending documents across all steps."""
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
