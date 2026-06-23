"""
Lab service — backs the OCR calibration screen (/lab/:id).

Lets the user compare, for a single document, how different text-recognition
methods perform on the SAME first-page image:
  - local Tesseract (in-process)
  - EasyOCR (via the external compute worker, if reachable)
  - any vision-capable AI provider, used here as a verbatim transcriber
and then have a "premium" provider judge which transcription is best.

Everything here is ephemeral: nothing is written to the documents table.
"""

import io
import json
import logging
import time
from typing import Optional

import httpx
from PIL import Image
from sqlalchemy import text as sqla_text
from sqlalchemy.orm import Session

from ..config import settings
from . import ai_vision, ai_analysis

log = logging.getLogger(__name__)

# Vision models, in the lab, transcribe rather than describe.
OCR_VISION_PROMPT = """\
Transcribe ALL text from this scanned document image, verbatim and complete.
Preserve the original line breaks and reading order. Do not translate, summarise,
or comment. Output ONLY the transcribed text — no labels, no markdown."""

JUDGE_SYSTEM = """\
You are an expert OCR quality evaluator. You are given several transcriptions of the
SAME document, each produced by a different method and identified by a label.
Judge how accurate and readable each transcription is — coherent words, correct
numbers, no garbled characters or nonsense. If a document image is provided, compare
the transcriptions against it; otherwise judge purely on internal readability.

Return ONLY a raw JSON object (no markdown fences):
{
  "rankings": [{"label": "<label>", "score": <0-100 int>, "comment": "<short reason>"}],
  "best": "<label of the best transcription>",
  "summary": "<one-sentence overall conclusion>"
}
Use the exact labels provided. Order "rankings" best-first."""


# ── First-page image ───────────────────────────────────────────────────────────

def load_image(filepath: str) -> bytes:
    """First page as resized JPEG bytes — the single image every method works on."""
    return ai_vision.load_first_page(filepath)


# ── Local / worker OCR ──────────────────────────────────────────────────────────

async def run_local_ocr(img_bytes: bytes, method: str) -> tuple[str, int]:
    """Run a local OCR engine on the image. Returns (text, elapsed_ms)."""
    start = time.perf_counter()
    if method == "tesseract":
        text = _tesseract(img_bytes)
    elif method == "easyocr":
        text = await _easyocr_worker(img_bytes)
    else:
        raise ValueError(f"Unknown OCR method: {method}")
    return text, int((time.perf_counter() - start) * 1000)


def _tesseract(img_bytes: bytes) -> str:
    import pytesseract
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    return pytesseract.image_to_string(img, lang=settings.ocr_languages).strip()


async def _easyocr_worker(img_bytes: bytes) -> str:
    url = f"{settings.external_ocr_url.rstrip('/')}/ocr"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            files={"file": ("page.jpg", img_bytes, "image/jpeg")},
            params={"engine": "easyocr", "languages": settings.ocr_languages},
        )
        resp.raise_for_status()
        return resp.json().get("text", "").strip()


async def worker_available() -> bool:
    """Probe the compute worker /health for an easyocr engine."""
    try:
        url = f"{settings.external_ocr_url.rstrip('/')}/health"
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return "easyocr" in resp.json().get("engines", [])
    except Exception:
        return False


# ── Vision OCR ──────────────────────────────────────────────────────────────────

async def run_vision_ocr(img_bytes: bytes, provider, db: Session) -> tuple[str, float, int]:
    """Transcribe the image with one vision provider. Returns (text, cost, elapsed_ms)."""
    start = time.perf_counter()
    text, tin, tout, cost = await ai_vision.run_vision(provider, img_bytes, OCR_VISION_PROMPT)
    ms = int((time.perf_counter() - start) * 1000)
    _update_stats(db, provider, tin, tout, cost)
    return text.strip(), cost, ms


# ── Judge ───────────────────────────────────────────────────────────────────────

async def judge(
    candidates: list[dict],
    provider,
    db: Session,
    img_bytes: Optional[bytes] = None,
) -> dict:
    """
    Ask a provider to rank the candidate transcriptions.

    candidates: [{"label": str, "text": str}, ...]
    img_bytes:  include the document image (premium-vision judging) or None (text-only).
    Returns the parsed judge JSON plus "cost".
    """
    blocks = "\n\n".join(
        f"=== Transcription [{c['label']}] ===\n{(c.get('text') or '').strip() or '(empty)'}"
        for c in candidates
    )
    user_msg = (
        f"Here are {len(candidates)} transcriptions of the same document. "
        f"Evaluate and rank them.\n\n{blocks}"
    )

    start = time.perf_counter()
    if img_bytes is not None:
        prompt = f"{JUDGE_SYSTEM}\n\n{user_msg}"
        raw, tin, tout, cost = await ai_vision.run_vision(provider, img_bytes, prompt)
    else:
        raw, tin, tout, cost = await ai_analysis.run_text(provider, JUDGE_SYSTEM, user_msg)
    ms = int((time.perf_counter() - start) * 1000)
    _update_stats(db, provider, tin, tout, cost)

    result = _parse_json(raw)
    result["cost"] = cost
    result["ms"] = ms
    return result


def _parse_json(raw: str) -> dict:
    """Parse judge output, tolerating markdown code fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return json.loads(text)


# ── Stats ───────────────────────────────────────────────────────────────────────

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
