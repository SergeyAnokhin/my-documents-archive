"""AI usage ledger — one helper to record every call to an AI provider / OCR engine.

Every model call site (analysis, vision, Q&A, batch jobs, OCR, embeddings, …) calls
`record_usage(...)`. Rows land in the `ai_usage` table and power the super-user usage
screen (services live in routers/admin_usage.py).

Recording must never break the calling pipeline — all failures are swallowed.
"""
import logging
from typing import Optional

from ..database import SessionLocal
from ..models import AIUsage

log = logging.getLogger(__name__)


def record_usage(
    *,
    usage_type: str,
    provider_type: str,
    model: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: Optional[float] = None,
    provider_name: Optional[str] = None,
    document_id: Optional[int] = None,
    status: str = "ok",
    detail: Optional[str] = None,
) -> None:
    """Append one usage row. Opens its own short-lived session; never raises."""
    db = SessionLocal()
    try:
        db.add(AIUsage(
            usage_type=usage_type,
            provider_type=provider_type or "unknown",
            provider_name=provider_name,
            model=model,
            tokens_in=int(tokens_in or 0),
            tokens_out=int(tokens_out or 0),
            cost_usd=cost_usd,
            document_id=document_id,
            status=status,
            detail=(detail or "")[:256] or None,
        ))
        db.commit()
    except Exception as e:  # pragma: no cover - logging must never break callers
        log.warning("record_usage failed: %s", e)
        db.rollback()
    finally:
        db.close()
