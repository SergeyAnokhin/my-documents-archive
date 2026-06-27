"""Shared helpers for the AI provider services (analysis + vision).

Keeps in one place what used to be copy-pasted between ai_analysis.py and
ai_vision.py: markdown-fence stripping, provider usage-stats updates, the
env-var provider stand-in, and the canonical document-type taxonomy.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text as sqla_text
from sqlalchemy.orm import Session

# Canonical document-type taxonomy — shared verbatim by the analysis and vision
# prompts so the two never drift apart.
DOCUMENT_TYPES_BLOCK = """\
    passport, national_id, driver_license, birth_certificate, death_certificate,
    marriage_certificate, divorce_certificate, residence_permit, visa,
    contract, agreement, power_of_attorney, court_document,
    invoice, bank_statement, receipt, tax_document, payslip,
    property_deed, title_certificate, insurance_policy,
    medical_certificate, prescription, medical_record,
    diploma, certificate, transcript, student_id,
    permit, license, registration, notarial_deed,
    letter, notice, announcement, photo, scan, unclassified"""


def strip_code_fences(raw: str) -> str:
    """Remove a wrapping ```…``` markdown fence from an LLM response, if present."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text


def update_provider_stats(
    db: Session, provider, tokens_in: int, tokens_out: int, cost: float
) -> None:
    """Accumulate token/cost usage onto a DB-backed AIProvider row.

    No-op for synthetic (env-var) providers, which have no integer id.
    """
    if not isinstance(getattr(provider, "id", None), int):
        return
    db.execute(
        sqla_text(
            "UPDATE ai_providers SET "
            "total_tokens_in  = total_tokens_in  + :tin, "
            "total_tokens_out = total_tokens_out + :tout, "
            "total_cost_usd   = total_cost_usd   + :cost "
            "WHERE id = :id"
        ),
        {"tin": tokens_in, "tout": tokens_out, "cost": cost, "id": provider.id},
    )
    db.commit()


@dataclass
class SyntheticProvider:
    """Stand-in for an AIProvider ORM object, built from env vars (no DB id → stats untracked)."""
    name: str
    provider_type: str
    api_key: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    id: None = None
    extra_params: Optional[dict] = None
