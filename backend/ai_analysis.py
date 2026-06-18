"""AI-powered document analysis: tags, summary, type, language, metadata.

Uses configurable AI providers (DeepSeek by default) to analyze OCR text
and generate structured metadata for each document."""

import json
import logging
import os
import re
from typing import Any

import requests

from backend.config import get_ai_config

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are DocIntel, an AI assistant that analyzes personal documents.
Your job is to extract structured information from OCR text of scanned family documents.
Documents may be in Russian, French, or English. OCR text may be imperfect.

Respond ONLY with valid JSON, no other text. The JSON must have exactly these fields:
{
  "summary": "2-3 sentence summary in the document's language",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "doc_type": "one of: invoice, contract, certificate, letter, medical, tax, bank, insurance, identity, legal, receipt, other",
  "language": "ru or fr or en",
  "doc_date": "YYYY-MM-DD or null if not found",
  "organization": "organization name or null",
  "amount": "amount with currency or null"
}

Be precise with dates, amounts, and organization names. If uncertain, use null.
Tags should be concise keywords capturing what the document is about."""

USER_PROMPT_TEMPLATE = """Analyze this document OCR text:

Filename: {filename}
OCR Text:
{ocr_text}

Return JSON:"""


# ── Client ──────────────────────────────────────────────

def _call_ai(messages: list[dict], config: dict | None = None) -> str:
    """Call the configured AI provider. Returns raw content string."""
    if config is None:
        config = get_ai_config()

    provider = config.get("provider", "deepseek")
    model = config.get("analysis_model", "deepseek-chat")
    api_key = config.get("api_key", "")

    if not api_key:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("No AI provider API key configured. Set DEEPSEEK_API_KEY or configure in AI settings.")

    if provider == "deepseek":
        return _call_deepseek(messages, model, api_key)
    elif provider == "openai":
        base_url = config.get("base_url", "https://api.openai.com/v1")
        return _call_openai_compatible(messages, model, api_key, base_url)
    else:
        # Fallback: try as OpenAI-compatible
        base_url = config.get("base_url", "https://api.deepseek.com/v1")
        return _call_openai_compatible(messages, model, api_key, base_url)


def _call_deepseek(messages: list[dict], model: str, api_key: str) -> str:
    """Call DeepSeek API."""
    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_openai_compatible(messages: list[dict], model: str, api_key: str, base_url: str) -> str:
    """Call any OpenAI-compatible API."""
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Analysis ─────────────────────────────────────────────

def analyze_document(ocr_text: str, filename: str = "") -> dict[str, Any]:
    """Analyze document OCR text and return structured metadata.

    Returns dict with: summary, tags, doc_type, language, doc_date, organization, amount.
    On failure, returns partial/default data."""
    if not ocr_text.strip():
        return _empty_result()

    try:
        response = _call_ai([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                filename=filename,
                ocr_text=ocr_text[:8000],  # Truncate for token limits
            )},
        ])
        return _parse_response(response)
    except Exception as e:
        logger.warning("AI analysis failed for %s: %s", filename, e)
        return _empty_result()


def _parse_response(response: str) -> dict[str, Any]:
    """Extract JSON from AI response, handling markdown code blocks."""
    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*', '', response.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return _empty_result()
        else:
            return _empty_result()

    return {
        "summary": data.get("summary", ""),
        "tags": data.get("tags", [])[:10],
        "doc_type": data.get("doc_type", ""),
        "language": data.get("language", ""),
        "doc_date": data.get("doc_date"),
        "organization": data.get("organization"),
        "amount": data.get("amount"),
    }


def _empty_result() -> dict[str, Any]:
    return {
        "summary": "",
        "tags": [],
        "doc_type": "",
        "language": "",
        "doc_date": None,
        "organization": None,
        "amount": None,
    }
