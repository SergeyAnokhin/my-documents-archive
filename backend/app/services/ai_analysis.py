"""
AI Analysis — extracts document metadata using a configured AI provider.

Output fields: summary, document_type, tags, language, organization, amount, amount_currency.
Called from indexer._run_analysis() after OCR completes.

Provider priority: all enabled DB providers with task_type "analysis" or "both",
sorted by sort_order ASC. Each is tried in turn; on error the next is attempted (failover).
Falls back to env-var providers if no DB providers are configured.
"""

import json
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text as sqla_text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AIProvider

log = logging.getLogger(__name__)

ANALYSIS_SYSTEM = """\
You are a document analysis assistant. Analyze the document text and return a JSON object with:
- "summary": 2-3 sentence summary in the document's original language
- "document_type": exactly one of: invoice, contract, certificate, letter, medical, tax, id, receipt, other
- "tags": array of 3-7 keyword strings
- "language": ISO 639-1 code ("ru", "fr", "en", "de", "uk", etc.)
- "organization": company or institution name, or null if absent
- "amount": numeric monetary value (no currency symbol), or null if absent
- "amount_currency": ISO 4217 code ("USD", "EUR", "RUB", "GBP"), or null if absent

Return ONLY the raw JSON object. No markdown fences, no explanation."""


@dataclass
class AnalysisResult:
    summary: str = ""
    document_type: str = "other"
    tags: list = field(default_factory=list)
    language: str = ""
    organization: Optional[str] = None
    amount: Optional[float] = None
    amount_currency: Optional[str] = None
    cost_usd: float = 0.0


async def analyze_document(
    ocr_text: str,
    db: Session,
    vision_description: Optional[str] = None,
) -> Optional[AnalysisResult]:
    """
    Run AI analysis on OCR text (and optionally vision description).
    Tries providers in priority order; returns first successful result.
    Returns None if no provider succeeds.
    """
    providers = _get_providers(db)
    if not providers:
        return None

    parts: list[str] = []
    if ocr_text and ocr_text.strip():
        parts.append(f"OCR Text:\n{ocr_text[:3500]}")
    if vision_description and vision_description.strip():
        parts.append(f"AI Vision Description:\n{vision_description}")
    user_msg = "\n\n".join(parts) or "(no text available)"

    for provider in providers:
        try:
            raw, tokens_in, tokens_out, cost = await _call_provider(provider, user_msg)
            result = _parse_result(raw)
            result.cost_usd = cost
            _update_stats(db, provider, tokens_in, tokens_out, cost)
            return result
        except Exception as e:
            log.warning("Analysis provider '%s' failed: %s", provider.name, e)

    log.error("All %d analysis provider(s) failed for this document", len(providers))
    return None


# ── Provider selection ─────────────────────────────────────────────────────────

@dataclass
class _Synthetic:
    """Stand-in for an AIProvider ORM object, built from env vars."""
    name: str
    provider_type: str
    api_key: str
    base_url: Optional[str]
    model: Optional[str] = None
    id: None = None  # no DB id → stats not tracked


def _get_providers(db: Session) -> list:
    """Return enabled analysis providers ordered by sort_order, with env-var fallback."""
    db_providers = (
        db.query(AIProvider)
        .filter(
            AIProvider.enabled == True,
            AIProvider.task_type.in_(["analysis", "both"]),
        )
        .order_by(AIProvider.sort_order)
        .all()
    )
    if db_providers:
        return db_providers

    # Env-var fallbacks (tried in order, stop at first available key)
    result = []
    for ptype, key, url in [
        ("anthropic",  settings.anthropic_api_key,  None),
        ("openai",     settings.openai_api_key,      None),
        ("gemini",     settings.gemini_api_key,      None),
        ("deepseek",   settings.deepseek_api_key,    "https://api.deepseek.com/v1"),
        ("openrouter", settings.openrouter_api_key,  "https://openrouter.ai/api/v1"),
    ]:
        if key:
            result.append(_Synthetic(name=ptype, provider_type=ptype, api_key=key, base_url=url))
    return result


# ── Stats tracking ─────────────────────────────────────────────────────────────

def _update_stats(db: Session, provider, tokens_in: int, tokens_out: int, cost: float) -> None:
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


# ── Provider dispatch ──────────────────────────────────────────────────────────

async def run_text(provider, system: str, user_msg: str) -> tuple[str, int, int, float]:
    """Send a system + user prompt to one text provider. Returns (text, tokens_in, tokens_out, cost)."""
    return await _call_provider(provider, user_msg, system)


async def _call_provider(provider, user_msg: str, system: str = ANALYSIS_SYSTEM) -> tuple[str, int, int, float]:
    """Return (raw_text, tokens_in, tokens_out, cost_usd)."""
    ptype = provider.provider_type
    if ptype == "anthropic":
        return await _call_anthropic(provider, user_msg, system)
    if ptype == "gemini":
        return await _call_gemini(provider, user_msg, system)
    return await _call_openai_compatible(provider, user_msg, system)


async def _call_anthropic(provider, user_msg: str, system: str = ANALYSIS_SYSTEM) -> tuple[str, int, int, float]:
    import anthropic
    model = getattr(provider, "model", None) or "claude-haiku-4-5-20251001"
    client = anthropic.AsyncAnthropic(api_key=provider.api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    tin  = resp.usage.input_tokens
    tout = resp.usage.output_tokens
    # Approximate pricing for Haiku; actual cost depends on model
    cost = tin * 0.00000080 / 1000 + tout * 0.00000400 / 1000
    return resp.content[0].text, tin, tout, cost


async def _call_openai_compatible(provider, user_msg: str, system: str = ANALYSIS_SYSTEM) -> tuple[str, int, int, float]:
    import openai
    model_defaults = {
        "openai":     "gpt-4o-mini",
        "deepseek":   "deepseek-chat",
        "openrouter": "openai/gpt-4o-mini",
    }
    model = getattr(provider, "model", None) or model_defaults.get(provider.provider_type, "gpt-4o-mini")
    client_kwargs: dict = {"api_key": provider.api_key}
    if getattr(provider, "base_url", None):
        client_kwargs["base_url"] = provider.base_url

    client = openai.AsyncOpenAI(**client_kwargs)
    create_kwargs: dict = {
        "model": model,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
    }
    if provider.provider_type == "openai":
        create_kwargs["response_format"] = {"type": "json_object"}

    resp = await client.chat.completions.create(**create_kwargs)
    text = resp.choices[0].message.content or ""
    tin = tout = 0
    cost = 0.0
    if resp.usage:
        tin  = resp.usage.prompt_tokens
        tout = resp.usage.completion_tokens
        cost = tin * 0.00000015 + tout * 0.0000006
    return text, tin, tout, cost


async def _call_gemini(provider, user_msg: str, system: str = ANALYSIS_SYSTEM) -> tuple[str, int, int, float]:
    import google.generativeai as genai
    model_name = getattr(provider, "model", None) or "gemini-1.5-flash"
    genai.configure(api_key=provider.api_key)
    gm = genai.GenerativeModel(model_name, system_instruction=system)
    resp = await asyncio.to_thread(
        gm.generate_content, user_msg,
        generation_config={"max_output_tokens": 1024},
    )
    return resp.text, 0, 0, 0.0


# ── Result parsing ─────────────────────────────────────────────────────────────

def _parse_result(raw: str) -> AnalysisResult:
    """Parse LLM output, tolerating markdown code fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])

    data = json.loads(text)
    amount = data.get("amount")
    return AnalysisResult(
        summary=str(data.get("summary", "")),
        document_type=str(data.get("document_type", "other")),
        tags=[str(t) for t in data.get("tags", [])],
        language=str(data.get("language", "")),
        organization=data.get("organization") or None,
        amount=float(amount) if amount is not None else None,
        amount_currency=data.get("amount_currency") or None,
    )
