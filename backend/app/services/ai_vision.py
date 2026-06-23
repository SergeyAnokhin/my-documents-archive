"""
AI Vision — Step 3 of the indexing pipeline.

Sends the document's first page to a vision-capable AI model and returns
a factual description. Result stored in Document.vision_description.

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
    Tries providers in priority order; returns (description_text, cost_usd) on first success.
    Returns None if no provider succeeds.
    """
    providers = _get_providers(db)
    if not providers:
        return None

    try:
        img_bytes = _load_first_page(filepath)
    except Exception as e:
        log.warning("Vision: cannot load image from %s: %s", filepath, e)
        return None

    b64 = base64.b64encode(img_bytes).decode()

    for provider in providers:
        try:
            ptype = provider.provider_type
            if ptype == "anthropic":
                text, tin, tout, cost = await _call_anthropic(provider, b64)
            elif ptype == "gemini":
                text, tin, tout, cost = await _call_gemini(provider, img_bytes)
            else:
                text, tin, tout, cost = await _call_openai_compat(provider, b64)
            _update_stats(db, provider, tin, tout, cost)
            return text, cost
        except Exception as e:
            log.warning("Vision provider '%s' failed: %s", provider.name, e)

    log.error("All %d vision provider(s) failed for %s", len(providers), filepath)
    return None


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
    id: None = None


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
        ("anthropic",  settings.anthropic_api_key,  None),
        ("openai",     settings.openai_api_key,      None),
        ("gemini",     settings.gemini_api_key,      None),
        ("openrouter", settings.openrouter_api_key,  "https://openrouter.ai/api/v1"),
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

async def _call_anthropic(provider, b64: str) -> tuple[str, int, int, float]:
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
    tin  = resp.usage.input_tokens
    tout = resp.usage.output_tokens
    cost = tin * 0.00000080 / 1000 + tout * 0.00000400 / 1000
    return resp.content[0].text, tin, tout, cost


async def _call_openai_compat(provider, b64: str) -> tuple[str, int, int, float]:
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
    tin = tout = 0
    cost = 0.0
    if resp.usage:
        tin  = resp.usage.prompt_tokens
        tout = resp.usage.completion_tokens
        cost = tin * 0.00000015 + tout * 0.0000006
    return text, tin, tout, cost


async def _call_gemini(provider, img_bytes: bytes) -> tuple[str, int, int, float]:
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
    return resp.text, 0, 0, 0.0
