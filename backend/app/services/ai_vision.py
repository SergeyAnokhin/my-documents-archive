"""
AI Vision — Step 3 of the indexing pipeline.

For capable models (OpenAI/Gemini/OpenRouter): sends the first page image and asks
for a full structured JSON (text + all analysis fields). If successful, the indexer
skips Step 4 (AI Analysis) entirely.

For Mistral OCR: returns plain text transcription; indexer still runs Analysis.

Only runs when 'enable_ai_vision' = 'true' in AppSettings (admin toggle).
Provider priority: all enabled DB providers with task_type "vision" or "both"
AND provider_type in VISION_CAPABLE, sorted by sort_order ASC. Failover on error.
Falls back to env-var providers if no DB providers are configured.
"""

import base64
import io
import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from PIL import Image
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AIProvider
from .pricing import estimate_cost
from .ai_analysis import AnalysisResult, coerce_analysis_fields
from .ai_common import (
    DOCUMENT_TYPES_BLOCK,
    SyntheticProvider,
    strip_code_fences,
    update_provider_stats,
)

log = logging.getLogger(__name__)

VISION_PROMPT = """\
You are analyzing a scanned document. Provide a concise factual description (3-5 sentences):
- What type of document is this?
- What key information is visible: dates, amounts, names, organizations, reference numbers?
- What language is the document in?
- Note any stamps, tables, or handwritten elements."""

# Combined vision+analysis prompt for capable (non-Mistral) models.
# Returns a single JSON with both verbatim text and all structured fields,
# so the indexer can skip the separate AI Analysis step entirely.
VISION_FULL_PROMPT = f"""\
Analyze this scanned document image. Return a single JSON object with these fields:

"text": verbatim transcription of ALL visible text, preserving line breaks and reading order
"summary": 2-3 sentence summary in the document's original language
"document_type": the single most specific type from this list:
{DOCUMENT_TYPES_BLOCK}
"document_type_confidence": 0.0-1.0 confidence in the type assignment
"tags": array of 3-7 keyword strings
"language": ISO 639-1 code ("ru", "fr", "en", "de", "uk", etc.)
"organization": company or institution name, or null
"amount": numeric monetary value (no currency symbol), or null
"amount_currency": ISO 4217 code ("USD", "EUR", "RUB", "GBP"), or null
"person_first_name": first name of the most important person, or null
"person_last_name": last name of the most important person, or null
"document_date": most significant date in YYYY-MM-DD format, or null
"short_title": 2-5 word filename slug, lowercase_with_underscores, no extension, max 40 chars

If the document contains no readable text (it is a photograph, illustration, or artwork), describe the visual content in "text" (subjects, scene, setting, notable elements) and use "photo" as the document_type. Derive the summary, tags, and other fields from that visual description.

Return ONLY the raw JSON object. No markdown fences, no explanation."""

class VisionFullResponse(BaseModel):
    text: str
    summary: str
    document_type: str
    document_type_confidence: float
    tags: list[str]
    language: str
    organization: Optional[str] = None
    amount: Optional[float] = None
    amount_currency: Optional[str] = None
    person_first_name: Optional[str] = None
    person_last_name: Optional[str] = None
    document_date: Optional[str] = None
    short_title: str


VISION_CAPABLE = {"openai", "gemini", "openrouter", "mistral", "openai_web"}

VISION_DEFAULTS = {
    "openai":     "gpt-4o-mini",
    "gemini":     "gemini-2.5-flash",
    "openrouter": "openai/gpt-4o-mini",
    "mistral":    "mistral-ocr-latest",
}

# Mistral OCR is billed per page (~$1 / 1000 pages), not per token.
MISTRAL_OCR_PRICE_PER_PAGE = 0.001


async def describe_document(
    filepath: str, db: Session
) -> Optional[tuple[str, Optional[AnalysisResult], float]]:
    """
    Describe/analyze document using a vision model.

    For capable (non-Mistral) providers: uses VISION_FULL_PROMPT to get both the
    verbatim transcription AND all structured analysis fields in one call.
    Returns (transcription_text, AnalysisResult, cost_usd).

    For Mistral OCR: returns (transcription_text, None, cost_usd) — the indexer
    must still run AI Analysis separately.

    Returns None if no provider is configured or all fail.
    """
    providers = _get_providers(db)
    if not providers:
        return None

    try:
        img_bytes = load_first_page(filepath, max_size=_get_max_image_size(db))
    except Exception as e:
        log.warning("Vision: cannot load image from %s: %s", filepath, e)
        return None

    for provider in providers:
        try:
            text, tin, tout, cost = await run_vision(provider, img_bytes, VISION_FULL_PROMPT, response_schema=VisionFullResponse)
            update_provider_stats(db, provider, tin, tout, cost)
            from .usage import record_usage
            record_usage(
                usage_type="vision",
                provider_type=provider.provider_type,
                provider_name=getattr(provider, "name", None),
                model=getattr(provider, "model", None),
                tokens_in=tin, tokens_out=tout, cost_usd=cost,
            )

            if provider.provider_type == "mistral":
                # Mistral OCR ignores the prompt and returns plain markdown.
                return text, None, cost

            data = parse_vision_full(text)
            if data and "text" in data:
                transcription = str(data.pop("text") or "").strip()
                return transcription, coerce_analysis_fields(data), cost

            # Model returned plain text (unexpected) — treat as description only.
            return text, None, cost
        except Exception as e:
            log.warning("Vision provider '%s' failed: %s", provider.name, e)

    log.error("All %d vision provider(s) failed for %s", len(providers), filepath)
    return None


def parse_vision_full(raw: str) -> Optional[dict]:
    """Parse VISION_FULL_PROMPT response. Returns the full dict or None on parse error."""
    try:
        data = json.loads(strip_code_fences(raw))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def run_vision(provider, img_bytes: bytes, prompt: str, json_mode: bool = False, response_schema=None) -> tuple[str, int, int, float]:
    """Send an image + prompt to one vision provider. Returns (text, tokens_in, tokens_out, cost)."""
    ptype = provider.provider_type
    if ptype == "gemini":
        return await _call_gemini(provider, img_bytes, prompt, json_mode=json_mode, response_schema=response_schema)
    if ptype == "mistral":
        return await _call_mistral_ocr(provider, img_bytes)
    if ptype == "openai_web":
        return await _call_chatgpt_web_vision(provider, img_bytes, prompt, json_mode=json_mode)
    b64 = base64.b64encode(img_bytes).decode()
    return await _call_openai_compat(provider, b64, prompt, json_mode=json_mode)


# ── Image loading ─────────────────────────────────────────────────────────────

def _get_max_image_size(db) -> int:
    """Read vision_max_image_size from AppSettings; default 1024."""
    from ..models import AppSettings
    try:
        row = db.query(AppSettings).filter(AppSettings.key == "vision_max_image_size").first()
        return int(row.value) if row else 1024
    except (ValueError, TypeError, Exception):
        return 1024


def load_first_page(filepath: str, max_size: int = 1024) -> bytes:
    """Return first document page as resized JPEG bytes (max_size on long side)."""
    path = Path(filepath)
    if path.suffix.lower() == ".pdf":
        img = _pdf_first_page(path)
    else:
        img = Image.open(filepath).convert("RGB")

    img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _pdf_first_page(path: Path) -> Image.Image:
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(str(path), dpi=150, first_page=1, last_page=1)
        if pages:
            return pages[0].convert("RGB")
    except Exception as e:
        log.warning("pdf2image failed for vision: %s", e)
    return Image.open(path).convert("RGB")


# ── Provider selection ────────────────────────────────────────────────────────

def _get_providers(db: Session) -> list:
    """Return enabled vision-capable providers ordered by sort_order, with env-var fallback."""
    db_providers = (
        db.query(AIProvider)
        .filter(
            AIProvider.enabled == True,
            AIProvider.task_type.in_(["vision", "both"]),
            AIProvider.provider_type.in_(VISION_CAPABLE),
        )
        .order_by(AIProvider.sort_order)
        .all()
    )
    if db_providers:
        return db_providers

    result = []
    for ptype, key, url in [
        ("openai",     settings.openai_api_key,     None),
        ("gemini",     settings.gemini_api_key,     None),
        ("openrouter", settings.openrouter_api_key, "https://openrouter.ai/api/v1"),
        ("mistral",    settings.mistral_api_key,    None),
    ]:
        if key:
            result.append(SyntheticProvider(ptype, ptype, key, url))
    return result


# ── Provider calls ────────────────────────────────────────────────────────────

async def _call_openai_compat(provider, b64: str, prompt: str = VISION_PROMPT, json_mode: bool = False) -> tuple[str, int, int, float]:
    import openai
    extra = getattr(provider, "extra_params", None) or {}
    model = getattr(provider, "model", None) or VISION_DEFAULTS.get(provider.provider_type, "gpt-4o-mini")
    _base_url_defaults = {
        "deepseek":   "https://api.deepseek.com/v1",
        "mistral":    "https://api.mistral.ai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }
    kwargs: dict = {"api_key": provider.api_key}
    base_url = getattr(provider, "base_url", None) or _base_url_defaults.get(provider.provider_type)
    if base_url:
        kwargs["base_url"] = base_url
    client = openai.AsyncOpenAI(**kwargs)
    create_kwargs: dict = {"model": model, "max_tokens": int(extra.get("max_tokens", 2048))}
    if "temperature" in extra:
        create_kwargs["temperature"] = float(extra["temperature"])
    if json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}
    resp = await client.chat.completions.create(
        **create_kwargs,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    text = resp.choices[0].message.content or ""
    tin = tout = 0
    cost = 0.0
    if resp.usage:
        tin  = resp.usage.prompt_tokens
        tout = resp.usage.completion_tokens
        cost = estimate_cost(model, tin, tout)
    return text, tin, tout, cost


def parse_mistral_ocr(data: dict, image_policy: str = "placeholder") -> tuple[str, float]:
    """Join per-page markdown, apply image_policy, return (text, cost_usd).

    image_policy:
      "placeholder" — replace ![img](url) with [изображение]
      "strip"       — remove image references entirely
    """
    import re
    text = "\n\n".join(p.get("markdown", "") for p in data.get("pages", [])).strip()
    pages = data.get("usage_info", {}).get("pages_processed", 1)

    if image_policy == "strip":
        text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
    else:  # "placeholder" (default)
        text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '[изображение]', text)

    return text, pages * MISTRAL_OCR_PRICE_PER_PAGE


async def _call_mistral_ocr(provider, img_bytes: bytes) -> tuple[str, int, int, float]:
    """Mistral OCR — dedicated document-transcription endpoint (not chat).
    Ignores the prompt; returns the page markdown as the description text."""
    import httpx
    extra = getattr(provider, "extra_params", None) or {}
    image_policy = extra.get("image_policy", "placeholder")
    include_image_base64 = bool(extra.get("include_image_base64", False))

    model = getattr(provider, "model", None) or VISION_DEFAULTS["mistral"]
    b64 = base64.b64encode(img_bytes).decode()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.mistral.ai/v1/ocr",
            headers={"Authorization": f"Bearer {provider.api_key}"},
            json={
                "model": model,
                "document": {"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"},
                "include_image_base64": include_image_base64,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    text, cost = parse_mistral_ocr(data, image_policy)
    return text, 0, 0, cost


async def _call_chatgpt_web_vision(provider, img_bytes: bytes, prompt: str, json_mode: bool = False) -> tuple[str, int, int, float]:
    """ChatGPT Web vision — sends image to chatgpt.com using OAuth access token."""
    from .chatgpt_web import vision_completion, ensure_fresh_token
    import base64 as b64_mod
    image_b64 = b64_mod.b64encode(img_bytes).decode()
    model = getattr(provider, "model", None) or "gpt-4o-mini"
    access_token = await ensure_fresh_token(provider)
    return await vision_completion(
        access_token=access_token,
        image_b64=image_b64,
        prompt=prompt,
        model=model,
        json_mode=json_mode,
    )


async def _call_gemini(provider, img_bytes: bytes, prompt: str = VISION_PROMPT, json_mode: bool = False, response_schema=None) -> tuple[str, int, int, float]:
    from google import genai
    from google.genai import types
    extra = getattr(provider, "extra_params", None) or {}
    model_name = getattr(provider, "model", None) or VISION_DEFAULTS["gemini"]
    client = genai.Client(api_key=provider.api_key)
    image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
    cfg_kwargs: dict = {"max_output_tokens": int(extra.get("max_tokens", 2048))}
    if "temperature" in extra:
        cfg_kwargs["temperature"] = float(extra["temperature"])
    if response_schema is not None:
        cfg_kwargs["response_schema"] = response_schema
    elif json_mode:
        cfg_kwargs["response_mime_type"] = "application/json"
    resp = await client.aio.models.generate_content(
        model=model_name,
        contents=[prompt, image_part],
        config=types.GenerateContentConfig(**cfg_kwargs),
    )
    um = getattr(resp, "usage_metadata", None)
    tin  = int(getattr(um, "prompt_token_count", 0) or 0)
    tout = int(getattr(um, "candidates_token_count", 0) or 0)
    cost = estimate_cost(model_name, tin, tout)
    return resp.text, tin, tout, cost
