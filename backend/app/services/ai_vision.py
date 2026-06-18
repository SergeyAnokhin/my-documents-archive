"""
AI Vision — Step 2 of the indexing pipeline.

Sends the document's first page to a vision-capable AI model and returns
a factual description. Result stored in Document.vision_description.

Only runs when 'enable_ai_vision' = 'true' in AppSettings (admin toggle).
"""

import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image
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

VISION_CAPABLE = {"anthropic", "openai", "gemini", "openrouter"}

VISION_DEFAULTS = {
    "anthropic":  "claude-haiku-4-5-20251001",
    "openai":     "gpt-4o-mini",
    "gemini":     "gemini-1.5-flash",
    "openrouter": "openai/gpt-4o-mini",
}


async def describe_document(filepath: str, db: Session) -> Optional[tuple[str, float]]:
    """
    Describe document using a vision model.
    Returns (description_text, cost_usd) or None if no provider available.
    """
    provider = _pick_provider(db)
    if not provider:
        return None

    try:
        img_bytes = _load_first_page(filepath)
    except Exception as e:
        log.warning("Vision: cannot load image from %s: %s", filepath, e)
        return None

    b64 = base64.b64encode(img_bytes).decode()

    ptype = provider.provider_type
    if ptype == "anthropic":
        return await _call_anthropic(provider, b64)
    if ptype == "gemini":
        return await _call_gemini(provider, img_bytes)
    return await _call_openai_compat(provider, b64)


# ── Image loading ─────────────────────────────────────────────────────────────

def _load_first_page(filepath: str) -> bytes:
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


def _pick_provider(db: Session):
    """Return first enabled vision-capable provider from DB, or env-var fallback."""
    p = (
        db.query(AIProvider)
        .filter(AIProvider.enabled == True,
                AIProvider.provider_type.in_(VISION_CAPABLE))
        .first()
    )
    if p:
        return p
    for ptype, key, url in [
        ("anthropic",  settings.anthropic_api_key,  ""),
        ("openai",     settings.openai_api_key,      ""),
        ("gemini",     settings.gemini_api_key,      ""),
        ("openrouter", settings.openrouter_api_key,  "https://openrouter.ai/api/v1"),
    ]:
        if key:
            return _Synthetic(ptype, ptype, key, url or None)
    return None


# ── Provider calls ────────────────────────────────────────────────────────────

async def _call_anthropic(provider, b64: str) -> tuple[str, float]:
    import anthropic
    model = getattr(provider, "model", None) or VISION_DEFAULTS["anthropic"]
    client = anthropic.AsyncAnthropic(api_key=provider.api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )
    text = resp.content[0].text
    cost = resp.usage.input_tokens * 0.00000025 + resp.usage.output_tokens * 0.00000125
    return text, cost


async def _call_openai_compat(provider, b64: str) -> tuple[str, float]:
    import openai
    model = getattr(provider, "model", None) or VISION_DEFAULTS.get(provider.provider_type, "gpt-4o-mini")
    kwargs: dict = {"api_key": provider.api_key}
    if getattr(provider, "base_url", None):
        kwargs["base_url"] = provider.base_url
    client = openai.AsyncOpenAI(**kwargs)
    resp = await client.chat.completions.create(
        model=model,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )
    text = resp.choices[0].message.content or ""
    cost = 0.0
    if resp.usage:
        cost = resp.usage.prompt_tokens * 0.00000015 + resp.usage.completion_tokens * 0.0000006
    return text, cost


async def _call_gemini(provider, img_bytes: bytes) -> tuple[str, float]:
    import google.generativeai as genai
    model_name = getattr(provider, "model", None) or VISION_DEFAULTS["gemini"]
    genai.configure(api_key=provider.api_key)
    gm = genai.GenerativeModel(model_name)
    image_part = {"mime_type": "image/jpeg", "data": img_bytes}
    resp = await asyncio.to_thread(
        gm.generate_content,
        [VISION_PROMPT, image_part],
        generation_config={"max_output_tokens": 512},
    )
    return resp.text, 0.0
