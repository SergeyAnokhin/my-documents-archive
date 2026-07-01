"""Async batch-OCR task runners — Mistral Batch API and Gemini Batch Mode.

Both submit a remote batch job, then poll every `poll_interval` seconds until the
provider finishes (up to 24–48 h), and write the transcription back to each
Document. Split out of routers/tasks.py to keep that router focused on CRUD.

This module holds the shared document-scope filter, the vision-vs-text routing
rule, and the Gemini batch API base URL — logic used by both provider
integrations. The actual runners live in their own files, one per provider:
`batch_ocr_mistral.py` (`run_batch_ocr_mistral`) and `batch_ocr_gemini.py`
(`run_batch_ocr_gemini`), each importing the shared helpers from here. See
docs/batch-ocr.md.
"""
from sqlalchemy import or_

from ..models import Document

_LOCAL_OCR_MODELS = {"tesseract", "easyocr"}


def _needs_vision(doc: Document) -> bool:
    """True if the document's image must be sent (no OCR text exists yet).

    Any existing OCR text is reused as-is — including local-engine
    (tesseract/easyocr) text: if it was kept rather than re-OCR'd, its quality
    is assumed acceptable, so only the (cheaper) text-only analysis pass runs.
    """
    return not (doc.ocr_text or "").strip()


def _scope_filter(query, scope: int):
    """Return query filtered to documents that qualify for re-OCR at the given scope (cumulative ≤ N).

    Scope 1: no extracted text at all.
    Scope 2: +documents with local-only OCR (Tesseract / EasyOCR).
    Scope 3: +documents that have AI OCR text but no AI analysis yet.
    Scope 4: all non-deleted documents (full reprocessing).
    """
    base = Document.is_deleted == False
    if scope <= 1:
        return query.filter(base, Document.ocr_text.is_(None))
    if scope == 2:
        return query.filter(
            base,
            or_(
                Document.ocr_text.is_(None),
                Document.ocr_model.is_(None),
                Document.ocr_model.in_(_LOCAL_OCR_MODELS),
            ),
        )
    if scope == 3:
        return query.filter(
            base,
            or_(
                Document.ocr_text.is_(None),
                Document.analysis_status != "done",
            ),
        )
    # scope 4: all
    return query.filter(base)


GEMINI_BATCH_BASE = "https://generativelanguage.googleapis.com"
