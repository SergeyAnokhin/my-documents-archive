"""
AI Analysis — extracts document metadata using a configured AI provider.

Output fields: summary, document_type, tags, language, organization, amount, amount_currency.
Called from indexer._run_analysis() after OCR completes.

Provider priority: first enabled DB provider → env-var fallbacks.
"""

import json
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Optional

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
    Returns AnalysisResult or None if no provider is available.
    """
    provider = _pick_provider(db)
    if not provider:
        return None

    parts: list[str] = []
    if ocr_text and ocr_text.strip():
        parts.append(f"OCR Text:\n{ocr_text[:3500]}")
    if vision_description and vision_description.strip():
        parts.append(f"AI Vision Description:\n{vision_description}")
    user_msg = "\n\n".join(parts) or "(no text available)"

    raw, cost = await _call_provider(provider, user_msg)
    result = _parse_result(raw)
    result.cost_usd = cost
    return result


# ── Provider selection ─────────────────────────────────────────────────────────

@dataclass
class _Synthetic:
    """Stand-in for an AIProvider ORM object, built from env vars."""
    name: str
    provider_type: str
    api_key: str
    base_url: Optional[str]
    model: Optional[str] = None


def _pick_provider(db: Session):
    """Return first enabled DB provider, or a synthetic one built from env vars."""
    p = db.query(AIProvider).filter(AIProvider.enabled == True).first()
    if p:
        return p
    for ptype, key, url in [
        ("anthropic",  settings.anthropic_api_key,  ""),
        ("openai",     settings.openai_api_key,      ""),
        ("gemini",     settings.gemini_api_key,      ""),
        ("deepseek",   settings.deepseek_api_key,    "https://api.deepseek.com/v1"),
        ("openrouter", settings.openrouter_api_key,  "https://openrouter.ai/api/v1"),
    ]:
        if key:
            return _Synthetic(name=ptype, provider_type=ptype, api_key=key,
                              base_url=url or None)
    return None


# ── Provider dispatch ──────────────────────────────────────────────────────────

async def _call_provider(provider, user_msg: str) -> tuple[str, float]:
    ptype = provider.provider_type
    if ptype == "anthropic":
        return await _call_anthropic(provider, user_msg)
    if ptype == "gemini":
        return await _call_gemini(provider, user_msg)
    return await _call_openai_compatible(provider, user_msg)


async def _call_anthropic(provider, user_msg: str) -> tuple[str, float]:
    import anthropic
    model = getattr(provider, "model", None) or "claude-haiku-4-5-20251001"
    client = anthropic.AsyncAnthropic(api_key=provider.api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=512,
        system=ANALYSIS_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = resp.content[0].text
    # Haiku: ~$0.25/M input, $1.25/M output
    cost = resp.usage.input_tokens * 0.00000025 + resp.usage.output_tokens * 0.00000125
    return text, cost


async def _call_openai_compatible(provider, user_msg: str) -> tuple[str, float]:
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
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": ANALYSIS_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    }
    # JSON mode is reliable on native OpenAI; skip for other compatible endpoints
    if provider.provider_type == "openai":
        create_kwargs["response_format"] = {"type": "json_object"}

    resp = await client.chat.completions.create(**create_kwargs)
    text = resp.choices[0].message.content or ""
    cost = 0.0
    if resp.usage:
        # gpt-4o-mini: $0.15/M input, $0.60/M output
        cost = resp.usage.prompt_tokens * 0.00000015 + resp.usage.completion_tokens * 0.0000006
    return text, cost


async def _call_gemini(provider, user_msg: str) -> tuple[str, float]:
    import google.generativeai as genai
    model_name = getattr(provider, "model", None) or "gemini-1.5-flash"
    genai.configure(api_key=provider.api_key)
    gm = genai.GenerativeModel(model_name, system_instruction=ANALYSIS_SYSTEM)
    resp = await asyncio.to_thread(
        gm.generate_content, user_msg,
        generation_config={"max_output_tokens": 512},
    )
    return resp.text, 0.0


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
