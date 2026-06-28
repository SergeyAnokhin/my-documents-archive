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
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image
from sqlalchemy import text as sqla_text
from sqlalchemy.orm import Session

from ..config import settings
from . import ai_vision, ai_analysis


def get_worker_url(db: Optional[Session] = None) -> str:
    """Return compute worker URL: from DB setting if set, else config default."""
    if db is not None:
        from ..models import AppSettings
        row = db.query(AppSettings).filter(AppSettings.key == "ocr_worker_url").first()
        if row and row.value:
            return row.value
    return settings.external_ocr_url

log = logging.getLogger(__name__)

# Vision models in the lab: transcribe AND extract structured fields in one call.
# Response is parsed as JSON; if the model returns plain text (e.g. Mistral OCR),
# the whole response is treated as the transcribed text with empty fields.
VISION_ANALYSIS_PROMPT = """\
Analyze this scanned document image and return a single JSON object with two keys:

"text": verbatim transcription of ALL text in the document, preserving original
line breaks and reading order. Do not translate, summarise, or add comments.
Output the raw transcription only — no labels, no markdown.

"fields": extracted metadata:
  "document_type": the single best type from this list — passport, national_id,
    driver_license, birth_certificate, death_certificate, marriage_certificate,
    divorce_certificate, residence_permit, visa, contract, agreement,
    power_of_attorney, court_document, invoice, bank_statement, receipt,
    tax_document, payslip, property_deed, title_certificate, insurance_policy,
    medical_certificate, prescription, medical_record, diploma, certificate,
    transcript, student_id, permit, license, registration, notarial_deed,
    letter, notice, announcement, photo, scan, unclassified
  "document_date": most significant date in YYYY-MM-DD format, or null
  "person_first_name": first name of the main person, or null
  "person_last_name": last name of the main person, or null
  "organization": company/institution name, or null
  "amount": numeric monetary value (no currency symbol), or null
  "amount_currency": ISO 4217 code ("USD", "EUR", "RUB"), or null
  "language": ISO 639-1 code ("ru", "en", "fr", etc.)

Return ONLY the raw JSON object. No markdown fences, no explanation."""

_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "ru": "Russian",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "zh": "Chinese",
}


def _judge_system(with_image: bool, language: str = "en") -> str:
    """Build the judge system prompt for the given mode and UI language."""
    lang_name = _LANG_NAMES.get(language, "English")

    if with_image:
        eval_ctx = (
            "A document image is also provided.\n\n"
            "Compare each transcription against the image: judge which ones capture the text "
            "most accurately, completely, and without garbled characters or missing words."
        )
        corrected_hint = "fix obvious errors using the image as the ground truth"
    else:
        eval_ctx = (
            "No document image is available — judge based on internal text quality only.\n\n"
            "Since these are OCR scan results, they may contain recognition errors: garbled "
            "characters, wrong words, broken word boundaries, or unreadable fragments. Evaluate "
            "which transcription reads most correctly and coherently — correct grammar, plausible "
            "words, consistent structure."
        )
        corrected_hint = "resolve conflicting readings in favour of the most plausible option"

    return f"""\
You are an expert OCR quality evaluator. You are given several transcriptions of the
SAME scanned document, each produced by a different recognition method and identified
by a label. {eval_ctx}

Only if combining the transcriptions would produce a meaningfully better result, provide
it under "corrected" ({corrected_hint}).
If the best transcription is already accurate enough, or the differences between
transcriptions are negligible, set "corrected" to an empty string — do not invent
improvements.

Also extract structured metadata from the best/corrected transcription and the image (if provided):
- "document_type": the single best type slug from this list — passport, national_id,
  driver_license, birth_certificate, death_certificate, marriage_certificate,
  divorce_certificate, residence_permit, visa, contract, agreement, power_of_attorney,
  court_document, invoice, bank_statement, receipt, tax_document, payslip,
  property_deed, title_certificate, insurance_policy, medical_certificate,
  prescription, medical_record, diploma, certificate, transcript, student_id,
  permit, license, registration, notarial_deed, letter, notice, announcement,
  photo, scan, unclassified
- "document_date": most significant date in YYYY-MM-DD format, or null
- "person_first_name": first name of the main person, or null
- "person_last_name": last name of the main person, or null
- "organization": company/institution name, or null
- "amount": numeric monetary value (no currency symbol), or null
- "amount_currency": ISO 4217 code ("USD", "EUR", "RUB"), or null
- "language": ISO 639-1 code ("ru", "en", "fr", etc.)

IMPORTANT: Write ALL evaluation text (comments, summary, corrected content) in {lang_name}.
Do NOT translate the original transcribed texts themselves.

Return ONLY a raw JSON object — no prose, no markdown, no explanation before or after it:
{{
  "rankings": [{{"label": "<label>", "score": <0-100 int>, "comment": "<short reason>"}}],
  "best": "<label of the best transcription>",
  "summary": "<one-sentence overall conclusion>",
  "corrected": "<improved text, or empty string if no meaningful improvement is possible>",
  "fields": {{
    "document_type": "<type slug>",
    "document_date": "<YYYY-MM-DD or null>",
    "person_first_name": "<name or null>",
    "person_last_name": "<name or null>",
    "organization": "<name or null>",
    "amount": <number or null>,
    "amount_currency": "<code or null>",
    "language": "<ISO code>"
  }}
}}
Use the exact labels provided. Order "rankings" best-first.
Your ENTIRE response must be the JSON object above and nothing else."""


# ── First-page image ───────────────────────────────────────────────────────────

def load_image(filepath: str) -> bytes:
    """First page as resized JPEG bytes — the single image every method works on."""
    return ai_vision.load_first_page(filepath)


# ── Image info & manipulation ──────────────────────────────────────────────────

_SAVE_FMT: dict[str, str] = {
    ".jpg": "JPEG", ".jpeg": "JPEG",
    ".png": "PNG", ".tiff": "TIFF", ".tif": "TIFF",
    ".webp": "WEBP", ".bmp": "BMP",
}


def get_image_info(filepath: str) -> dict:
    """Return width, height, file_size, format, can_adjust_quality for the document."""
    path = Path(filepath)
    file_size = path.stat().st_size
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            img = ai_vision._pdf_first_page(path)
            return {"width": img.width, "height": img.height,
                    "file_size": file_size, "format": "PDF",
                    "can_adjust_quality": False}
        except Exception:
            return {"width": 0, "height": 0,
                    "file_size": file_size, "format": "PDF",
                    "can_adjust_quality": False}
    with Image.open(filepath) as img:
        fmt = (img.format or suffix.strip(".")).upper()
        w, h = img.size
    can_quality = fmt in ("JPEG", "JPG", "PNG", "WEBP")
    return {"width": w, "height": h, "file_size": file_size,
            "format": fmt, "can_adjust_quality": can_quality}


def _open_doc_image(filepath: str) -> Image.Image:
    """Open document as RGB PIL Image (first page for PDFs)."""
    path = Path(filepath)
    if path.suffix.lower() == ".pdf":
        return ai_vision._pdf_first_page(path)
    return Image.open(filepath).convert("RGB")


def _apply_transforms(
    img: Image.Image,
    crop: Optional[dict],
    scale: Optional[float],
    rotation: Optional[int],
) -> Image.Image:
    if crop:
        x = max(0, int(crop.get("x", 0)))
        y = max(0, int(crop.get("y", 0)))
        w = max(1, int(crop.get("w", img.width)))
        h = max(1, int(crop.get("h", img.height)))
        x = min(x, img.width - 1)
        y = min(y, img.height - 1)
        w = min(w, img.width - x)
        h = min(h, img.height - y)
        img = img.crop((x, y, x + w, y + h))
    if scale is not None and 0 < scale < 1.0:
        new_w = max(1, round(img.width * scale))
        new_h = max(1, round(img.height * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
    if rotation and rotation % 360 != 0:
        # PIL rotates counter-clockwise; negate for clockwise user-facing rotation
        img = img.rotate(-rotation % 360, expand=True)
    return img


def preview_transform(
    filepath: str,
    crop: Optional[dict],
    scale: Optional[float],
    quality: Optional[int],
    rotation: Optional[int] = None,
) -> tuple[bytes, int, int]:
    """Return (jpeg_bytes, new_width, new_height) for a transform preview."""
    img = _open_doc_image(filepath)
    img = _apply_transforms(img, crop, scale, rotation)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=max(10, min(95, quality or 85)))
    return buf.getvalue(), img.width, img.height


def apply_transform(
    filepath: str,
    crop: Optional[dict],
    scale: Optional[float],
    quality: Optional[int],
    rotation: Optional[int] = None,
) -> tuple[int, int, int]:
    """
    Apply transform permanently to the file.
    Returns (new_width, new_height, new_file_size).
    """
    path = Path(filepath)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        raise ValueError("Cannot modify PDF files")

    with Image.open(filepath) as img_orig:
        original_format = img_orig.format
        img = img_orig.convert("RGB")

    img = _apply_transforms(img, crop, scale, rotation)

    save_fmt = _SAVE_FMT.get(suffix, original_format or "JPEG")
    q = max(10, min(95, quality or 85))
    save_kwargs: dict = {}
    if save_fmt == "JPEG":
        save_kwargs = {"quality": q, "optimize": True}
    elif save_fmt == "PNG":
        save_kwargs = {"compress_level": max(0, min(9, round((100 - q) / 100 * 9)))}
    elif save_fmt == "WEBP":
        save_kwargs = {"quality": q}

    img.save(filepath, format=save_fmt, **save_kwargs)
    new_size = path.stat().st_size
    return img.width, img.height, new_size


# ── Local / worker OCR ──────────────────────────────────────────────────────────

async def run_local_ocr(img_bytes: bytes, method: str, db: Optional[Session] = None) -> tuple[str, int]:
    """Run a local OCR engine on the image. Returns (text, elapsed_ms)."""
    start = time.perf_counter()
    if method == "tesseract":
        text = _tesseract(img_bytes)
    elif method == "easyocr":
        text = await _easyocr_worker(img_bytes, get_worker_url(db))
    else:
        raise ValueError(f"Unknown OCR method: {method}")
    return text, int((time.perf_counter() - start) * 1000)


def _tesseract(img_bytes: bytes) -> str:
    import pytesseract
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    return pytesseract.image_to_string(img, lang=settings.ocr_languages).strip()


async def _easyocr_worker(img_bytes: bytes, base_url: str = "") -> str:
    url = f"{(base_url or settings.external_ocr_url).rstrip('/')}/ocr"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            files={"file": ("page.jpg", img_bytes, "image/jpeg")},
            params={"engine": "easyocr", "languages": settings.ocr_languages},
        )
        resp.raise_for_status()
        return resp.json().get("text", "").strip()


async def worker_status(db: Optional[Session] = None) -> dict:
    """Probe the compute worker /health and return detailed status."""
    worker_url = get_worker_url(db)
    try:
        url = f"{worker_url.rstrip('/')}/health"
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            engines = resp.json().get("engines", [])
            return {
                "url": worker_url,
                "reachable": True,
                "engines": engines,
                "worker_available": "easyocr" in engines,
            }
    except Exception:
        return {
            "url": worker_url,
            "reachable": False,
            "engines": [],
            "worker_available": False,
        }


async def worker_available(db: Optional[Session] = None) -> bool:
    """Return True only if the compute worker is reachable and has easyocr."""
    status = await worker_status(db)
    return status["worker_available"]


# ── Vision OCR ──────────────────────────────────────────────────────────────────

def _parse_vision_analysis(raw: str) -> tuple[str, dict]:
    """
    Parse the combined vision+analysis JSON response.
    Returns (transcribed_text, fields_dict).
    Falls back to (raw, {}) when the model returns plain text (e.g. Mistral OCR).
    """
    stripped = raw.strip()
    # Strip markdown fences if present
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        stripped = "\n".join(lines[1:end])
    try:
        data = json.loads(stripped)
        text = str(data.get("text") or "").strip()
        fields = data.get("fields") or {}
        if not isinstance(fields, dict):
            fields = {}
        return text or stripped, fields
    except Exception:
        return stripped, {}


async def run_vision_ocr(img_bytes: bytes, provider, db: Session) -> tuple[str, dict, float, int, int, int]:
    """
    Transcribe the image and extract document fields with one vision provider.
    Returns (text, fields, cost, elapsed_ms, tokens_in, tokens_out).
    """
    start = time.perf_counter()
    raw, tin, tout, cost = await ai_vision.run_vision(provider, img_bytes, VISION_ANALYSIS_PROMPT)
    ms = int((time.perf_counter() - start) * 1000)
    _update_stats(db, provider, tin, tout, cost)
    text, fields = _parse_vision_analysis(raw)
    return text, fields, cost, ms, tin, tout


# ── Judge ───────────────────────────────────────────────────────────────────────

async def judge(
    candidates: list[dict],
    provider,
    db: Session,
    img_bytes: Optional[bytes] = None,
    language: str = "en",
) -> dict:
    """
    Ask a provider to rank the candidate transcriptions.

    candidates: [{"label": str, "text": str}, ...]
    img_bytes:  include the document image (premium-vision judging) or None (text-only).
    language:   UI language code — judge will write its analysis in that language.
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

    system = _judge_system(img_bytes is not None, language)
    provider_label = (
        f"{getattr(provider, 'name', '?')} "
        f"[{provider.provider_type}/{getattr(provider, 'model', None) or 'default'}]"
    )
    log.info(
        "Judge: calling %s, candidates=%d, with_image=%s",
        provider_label, len(candidates), img_bytes is not None,
    )
    start = time.perf_counter()
    try:
        if img_bytes is not None:
            prompt = f"{system}\n\n{user_msg}"
            raw, tin, tout, cost = await ai_vision.run_vision(provider, img_bytes, prompt)
        else:
            raw, tin, tout, cost = await ai_analysis.run_text(provider, system, user_msg)
    except Exception as e:
        # Paid external service — log full error so issues are cheap to diagnose.
        log.error("Judge: %s API call failed: %s", provider_label, e)
        raise
    ms = int((time.perf_counter() - start) * 1000)
    _update_stats(db, provider, tin, tout, cost)
    log.info(
        "Judge: %s — %d ms, tokens in=%d out=%d, cost=$%.5f",
        provider_label, ms, tin, tout, cost,
    )

    result = _parse_json(raw)
    result["cost"] = cost
    result["ms"] = ms
    result["tokens_in"] = tin
    result["tokens_out"] = tout
    # Ensure fields is a dict or None
    if "fields" in result and not isinstance(result["fields"], dict):
        result["fields"] = None
    return result


def _parse_json(raw: str) -> dict:
    """Parse judge output, tolerating markdown code fences and surrounding prose."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Model may have wrapped the JSON in prose — try to extract the object.
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    log.error(
        "Judge: model returned non-JSON response (%d chars):\n%.3000s",
        len(raw), raw,
    )
    raise ValueError(
        f"Judge model did not return valid JSON — got {len(raw)} chars of prose"
    )


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
