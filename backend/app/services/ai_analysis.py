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

from sqlalchemy.orm import Session

from ..config import settings
from ..models import AIProvider
from .pricing import estimate_cost
from .ai_common import (
    DOCUMENT_TYPES_BLOCK,
    SyntheticProvider,
    strip_code_fences,
    update_provider_stats,
)

log = logging.getLogger(__name__)

ANALYSIS_SYSTEM = f"""\
You are a document analysis assistant. Analyze the document text and return a JSON object with:
- "summary": 2-3 sentence summary in the document's original language
- "document_type": the single most specific type from this list:
{DOCUMENT_TYPES_BLOCK}
  Use "unclassified" if the document does not clearly fit any listed category.
- "document_type_confidence": 0.0-1.0 how confident you are in the type assignment
- "tags": array of 3-7 keyword strings
- "language": ISO 639-1 code ("ru", "fr", "en", "de", "uk", etc.)
- "organization": company or institution name, or null if absent
- "amount": numeric monetary value (no currency symbol), or null if absent
- "amount_currency": ISO 4217 code ("USD", "EUR", "RUB", "GBP"), or null if absent
- "person_first_name": first name of the most important person in the document, or null if absent
- "person_last_name": last name of the most important person in the document, or null if absent
- "document_date": the most significant date found in the document in YYYY-MM-DD format, or null if absent
- "short_title": 2-5 word filename slug, lowercase_with_underscores, no extension, max 40 chars (e.g. "passport_ivanov_2024", "lease_agreement_paris", "tax_return_2023")

Return ONLY the raw JSON object. No markdown fences, no explanation."""

SUGGEST_TYPES_SYSTEM = """\
You are a document classification assistant.
Given a document description and a list of existing document types, suggest the 3 most appropriate types.

Return ONLY a JSON array with exactly 3 objects:
[
  {"type": "type_slug", "confidence": 0.9, "reason": "brief reason"},
  {"type": "type_slug", "confidence": 0.6, "reason": "brief reason"},
  {"type": "type_slug", "confidence": 0.3, "reason": "brief reason"}
]

Rules:
- Prefer types from the existing list when they fit; suggest new specific types only when none fit
- type_slug: lowercase with underscores (e.g. "passport", "birth_certificate", "bank_statement")
- confidence: 0.0-1.0
- reason: one concise sentence in the document's own language
- Return only raw JSON, no markdown fences"""


@dataclass
class AnalysisResult:
    summary: str = ""
    document_type: str = "unclassified"
    document_type_confidence: float = 0.0
    tags: list = field(default_factory=list)
    language: str = ""
    organization: Optional[str] = None
    amount: Optional[float] = None
    amount_currency: Optional[str] = None
    person_first_name: Optional[str] = None
    person_last_name: Optional[str] = None
    document_date: Optional[str] = None  # YYYY-MM-DD string
    short_title: str = ""
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
            update_provider_stats(db, provider, tokens_in, tokens_out, cost)
            return result
        except Exception as e:
            log.warning("Analysis provider '%s' failed: %s", provider.name, e)

    log.error("All %d analysis provider(s) failed for this document", len(providers))
    return None


# ── Provider selection ─────────────────────────────────────────────────────────

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
        ("openai",     settings.openai_api_key,      None),
        ("gemini",     settings.gemini_api_key,      None),
        ("deepseek",   settings.deepseek_api_key,    "https://api.deepseek.com/v1"),
        ("openrouter", settings.openrouter_api_key,  "https://openrouter.ai/api/v1"),
    ]:
        if key:
            result.append(SyntheticProvider(name=ptype, provider_type=ptype, api_key=key, base_url=url))
    return result


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
    cost = estimate_cost(model, tin, tout)
    return resp.content[0].text, tin, tout, cost


async def _call_openai_compatible(provider, user_msg: str, system: str = ANALYSIS_SYSTEM) -> tuple[str, int, int, float]:
    import openai
    model_defaults = {
        "openai":     "gpt-4o-mini",
        "deepseek":   "deepseek-chat",
        "openrouter": "openai/gpt-4o-mini",
        "mistral":    "mistral-small-latest",
    }
    base_url_defaults = {
        "deepseek":   "https://api.deepseek.com/v1",
        "mistral":    "https://api.mistral.ai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }
    model = getattr(provider, "model", None) or model_defaults.get(provider.provider_type, "gpt-4o-mini")
    client_kwargs: dict = {"api_key": provider.api_key}
    base_url = getattr(provider, "base_url", None) or base_url_defaults.get(provider.provider_type)
    if base_url:
        client_kwargs["base_url"] = base_url

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
        cost = estimate_cost(model, tin, tout)
    return text, tin, tout, cost


async def _call_gemini(provider, user_msg: str, system: str = ANALYSIS_SYSTEM) -> tuple[str, int, int, float]:
    import google.generativeai as genai
    model_name = getattr(provider, "model", None) or "gemini-2.5-flash"
    genai.configure(api_key=provider.api_key)
    gm = genai.GenerativeModel(model_name, system_instruction=system)
    resp = await asyncio.to_thread(
        gm.generate_content, user_msg,
        generation_config={"max_output_tokens": 1024},
    )
    um = getattr(resp, "usage_metadata", None)
    tin  = int(getattr(um, "prompt_token_count", 0) or 0)
    tout = int(getattr(um, "candidates_token_count", 0) or 0)
    cost = estimate_cost(model_name, tin, tout)
    return resp.text, tin, tout, cost


# ── Result parsing ─────────────────────────────────────────────────────────────

def coerce_analysis_fields(data: dict) -> AnalysisResult:
    """Build an AnalysisResult from a parsed JSON dict, coercing/normalising field types.

    Shared by `_parse_result` (text analysis) and `ai_vision` (combined vision+analysis),
    so both produce identical document metadata from the same field names.
    """
    amount = data.get("amount")
    confidence = data.get("document_type_confidence")
    return AnalysisResult(
        summary=str(data.get("summary") or ""),
        document_type=str(data.get("document_type") or "unclassified"),
        document_type_confidence=float(confidence) if confidence is not None else 0.0,
        tags=[str(t) for t in (data.get("tags") or [])],
        language=str(data.get("language") or ""),
        organization=data.get("organization") or None,
        amount=float(amount) if amount is not None else None,
        amount_currency=data.get("amount_currency") or None,
        person_first_name=data.get("person_first_name") or None,
        person_last_name=data.get("person_last_name") or None,
        document_date=data.get("document_date") or None,
        short_title=str(data.get("short_title") or "")[:40],
    )


def _parse_result(raw: str) -> AnalysisResult:
    """Parse LLM output, tolerating markdown code fences."""
    return coerce_analysis_fields(json.loads(strip_code_fences(raw)))


async def suggest_document_types(
    summary: str,
    ocr_text: str,
    existing_types: list[str],
    db: Session,
) -> list[dict]:
    """Return up to 3 type suggestions from the LLM for a given document."""
    providers = _get_providers(db)
    if not providers:
        return []

    types_str = ", ".join(sorted(set(existing_types))) if existing_types else "(none yet)"
    user_msg = (
        f"Existing types: {types_str}\n\n"
        f"Document summary: {summary or '(no summary)'}\n\n"
        f"OCR text excerpt:\n{(ocr_text or '')[:1200]}"
    )

    for provider in providers:
        try:
            raw, _, _, _ = await _call_provider(provider, user_msg, SUGGEST_TYPES_SYSTEM)
            data = json.loads(strip_code_fences(raw))
            if isinstance(data, list):
                return data[:3]
        except Exception as e:
            log.warning("Suggest-types provider '%s' failed: %s", provider.name, e)

    return []
