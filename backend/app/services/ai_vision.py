"""
AI Vision — Step 3 of the indexing pipeline.

Sends the document's first page to a vision-capable AI model and returns
a factual description (or, for Mistral OCR, a verbatim transcription).
Result stored in Document.vision_description.

Only runs when 'enable_ai_vision' = 'true' in AppSettings (admin toggle).
Provider priority: all enabled DB providers with task_type "vision" or "both"
AND provider_type in VISION_CAPABLE, sorted by sort_order ASC. Failover on error.
Falls back to env-var providers if no DB providers are configured.
"""

import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image
from sqlalchemy import text as sqla_text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AIProvider

log = logging.getLogger(__name__)

VISION_PROMPT = """\
You are analyzing a scanned document. Provide a concise factual description (3-5 sentences):
- What type of document is this?
- What key information is visible: dates, amounts, names, organizations, reference numbers?
- What language is the document in?
- Note any stamps, tables, or handwritten elements."""

VISION_CAPABLE = {"anthropic", "openai", "gemini", "openrouter", "mistral"}

VISION_DEFAULTS = {
    "anthropic":  "claude-haiku-4-5-20251001",
    "openai":     "gpt-4o-mini",
    "gemini":     "gemini-2.5-flash",
    "openrouter": "openai/gpt-4o-mini",
    "mistral":    "mistral-ocr-latest",
}

# Mistral OCR is billed per page (~$1 / 1000 pages), not per token.
MISTRAL_OCR_PRICE_PER_PAGE = 0.001


async def describe_document(filepath: str, db: Session) -> Optional[tuple[str, float]]:
    """
    Describe document using a vision model.
    Tries providers in priority order; returns (description_text, cost_usd) on first success.
    Returns None if no provider succeeds.
    """
    providers = _get_providers(db)
    if not providers:
        return None

    try:
        img_bytes = load_first_page(filepath)
    except Exception as e:
        log.warning("Vision: cannot load image from %s: %s", filepath, e)
        return None

    for provider in providers:
        try:
            text, tin, tout, cost = await run_vision(provider, img_bytes, VISION_PROMPT)
            _update_stats(db, provider, tin, tout, cost)
            return text, cost
        except Exception as e:
            log.warning("Vision provider '%s' failed: %s", provider.name, e)

    log.error("All %d vision provider(s) failed for %s", len(providers), filepath)
    return None


async def run_vision(provider, img_bytes: bytes, prompt: str) -> tuple[str, int, int, float]:
    """Send an image + prompt to one vision provider. Returns (text, tokens_in, tokens_out, cost)."""
    ptype = provider.provider_type
    if ptype == "anthropic":
        b64 = base64.b64encode(img_bytes).decode()
        return await _call_anthropic(provider, b64, prompt)
    if ptype == "gemini":
        return await _call_gemini(provider, img_bytes, prompt)
    if ptype == "mistral":
        return await _call_mistral_ocr(provider, img_bytes)
    b64 = base64.b64encode(img_bytes).decode()
    return await _call_openai_compat(provider, b64, prompt)


# ── Image loading ─────────────────────────────────────────────────────────────

def load_first_page(filepath: str) -> bytes:
    """Return first document page as resized JPEG bytes (max 1024px)."""
    path = Path(filepath)
    if path.suffix.lower() == ".pdf":
        img = _pdf_first_page(path)
    else:
        img = Image.open(filepath).convert("RGB")

    img.thumbnail((1024, 1024), Image.LANCZOS)
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

@dataclass
class _Synthetic:
    name: str
    provider_type: str
    api_key: str
    base_url: Optional[str]
    model: Optional[str] = None
    id: None = None
    extra_params: Optional[dict] = None


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
        ("openai",     settings.openai_api_key,      None),
        ("gemini",     settings.gemini_api_key,      None),
        ("openrouter", settings.openrouter_api_key,  "https://openrouter.ai/api/v1"),
        ("mistral",    settings.mistral_api_key,     None),
    ]:
        if key:
            result.append(_Synthetic(ptype, ptype, key, url))
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


# ── Provider calls ────────────────────────────────────────────────────────────

async def _call_anthropic(provider, b64: str, prompt: str = VISION_PROMPT) -> tuple[str, int, int, float]:
    import anthropic
    extra = getattr(provider, "extra_params", None) or {}
    model = getattr(provider, "model", None) or VISION_DEFAULTS["anthropic"]
    max_tokens = int(extra.get("max_tokens", 2048))
    kwargs: dict = {"model": model, "max_tokens": max_tokens}
    if "temperature" in extra:
        kwargs["temperature"] = float(extra["temperature"])
    client = anthropic.AsyncAnthropic(api_key=provider.api_key)
    resp = await client.messages.create(
        **kwargs,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    tin  = resp.usage.input_tokens
    tout = resp.usage.output_tokens
    cost = tin * 0.00000080 / 1000 + tout * 0.00000400 / 1000
    return resp.content[0].text, tin, tout, cost


async def _call_openai_compat(provider, b64: str, prompt: str = VISION_PROMPT) -> tuple[str, int, int, float]:
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
        cost = tin * 0.00000015 + tout * 0.0000006
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


async def _call_gemini(provider, img_bytes: bytes, prompt: str = VISION_PROMPT) -> tuple[str, int, int, float]:
    import google.generativeai as genai
    extra = getattr(provider, "extra_params", None) or {}
    model_name = getattr(provider, "model", None) or VISION_DEFAULTS["gemini"]
    genai.configure(api_key=provider.api_key)
    gm = genai.GenerativeModel(model_name)
    image_part = {"mime_type": "image/jpeg", "data": img_bytes}
    gen_cfg: dict = {"max_output_tokens": int(extra.get("max_tokens", 2048))}
    if "temperature" in extra:
        gen_cfg["temperature"] = float(extra["temperature"])
    resp = await asyncio.to_thread(
        gm.generate_content,
        [prompt, image_part],
        generation_config=gen_cfg,
    )
    return resp.text, 0, 0, 0.0
