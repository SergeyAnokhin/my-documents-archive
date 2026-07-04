"""Lazy document-indexing plan and cost preview."""

from pathlib import Path

from sqlalchemy.orm import Session

from ..models import AIProvider, Document
from .provider_models import KNOWN_MODELS, _gemini_infer_pricing

STRATEGIES = {"mistral_gemini", "local_gemini", "gemini_complete"}
NATIVE_SUFFIXES = {".docx", ".txt"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"}


def _has_text(doc: Document) -> bool:
    return bool((doc.ocr_text or "").strip())


def _estimated_pages(doc: Document) -> int:
    suffix = Path(doc.filepath).suffix.lower()
    return 3 if suffix == ".pdf" else 1


def _gemini_prices(provider: AIProvider | None) -> tuple[float, float]:
    if not provider:
        return 0.0, 0.0
    info = KNOWN_MODELS.get(provider.model or "")
    if not info and provider.provider_type == "gemini":
        info = _gemini_infer_pricing(provider.model or "")
    return float((info or {}).get("in") or 0.0) / 2, float((info or {}).get("out") or 0.0) / 2


def build_index_plan(
    db: Session,
    strategy: str,
    limit: int = 500,
    gemini_provider_id: int | None = None,
) -> dict:
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown indexing strategy: {strategy}")
    candidates = (
        db.query(Document)
        .filter(Document.is_deleted == False, Document.analysis_status != "done")
        .order_by(Document.id)
        .limit(max(1, min(limit, 5000)))
        .all()
    )
    with_text = [doc for doc in candidates if _has_text(doc)]
    missing_text = [doc for doc in candidates if not _has_text(doc)]
    native = [doc for doc in missing_text if Path(doc.filepath).suffix.lower() in NATIVE_SUFFIXES]
    visual = [doc for doc in missing_text if doc not in native]
    pages = sum(_estimated_pages(doc) for doc in visual)

    gemini_vision = len(visual) if strategy == "gemini_complete" else 0
    mistral = len(visual) if strategy == "mistral_gemini" else 0
    local = len(visual) if strategy == "local_gemini" else 0
    gemini_text = len(with_text) + len(native) + (0 if strategy == "gemini_complete" else len(visual))

    provider = None
    if gemini_provider_id:
        provider = db.query(AIProvider).filter(AIProvider.id == gemini_provider_id).first()
    price_in, price_out = _gemini_prices(provider)
    chars = sum(len(doc.ocr_text or "") for doc in with_text)
    estimated_input_tokens = chars // 4 + len(candidates) * 700 + len(missing_text) * 1800
    estimated_output_tokens = len(candidates) * 450
    gemini_cost = estimated_input_tokens / 1_000_000 * price_in + estimated_output_tokens / 1_000_000 * price_out
    mistral_cost = pages * 0.002 if strategy == "mistral_gemini" else 0.0

    total_active = db.query(Document).filter(Document.is_deleted == False).count()
    return {
        "strategy": strategy,
        "document_ids": [doc.id for doc in candidates],
        "existing_text_ids": [doc.id for doc in with_text],
        "native_text_ids": [doc.id for doc in native],
        "visual_ocr_ids": [doc.id for doc in visual],
        "total_candidates": len(candidates),
        "already_has_text": len(with_text),
        "native_text": len(native),
        "needs_visual_ocr": len(visual),
        "mistral_ocr": mistral,
        "local_ocr": local,
        "gemini_vision": gemini_vision,
        "gemini_text": gemini_text,
        "estimated_pages": pages,
        "already_complete": max(0, total_active - len(candidates)),
        "estimated_cost_usd": round(mistral_cost + gemini_cost, 4),
        "estimated_mistral_cost_usd": round(mistral_cost, 4),
        "estimated_gemini_cost_usd": round(gemini_cost, 4),
        "cost_is_estimate": True,
        "page_limit": 3,
    }
