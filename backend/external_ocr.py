"""External OCR — AI-powered text extraction for difficult documents.

When Tesseract produces poor results (empty text, low confidence),
fall back to a multimodal LLM (DeepSeek Vision, OpenAI, etc.) to
extract text directly from document images.

Supports: JPEG, PNG, PDF (first page), TIFF, WEBP.
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests

from backend.config import get_ai_config

logger = logging.getLogger(__name__)

OCR_SYSTEM_PROMPT = """You are a professional OCR engine. Extract ALL text from this document image.
Rules:
- Return ONLY the extracted text, no commentary, no markdown
- Preserve the original language (Russian, French, English, etc.)
- Keep the document's structure: line breaks, paragraphs, tables as text
- If you see numbers, dates, names — include them exactly as shown
- If the image contains no text, return "[NO TEXT FOUND]"
- Do NOT translate — keep the original language"""


def external_ocr(
    file_path: Path,
    model: Optional[str] = None,
    max_tokens: int = 2048,
    language_hint: str = "",
) -> str:
    """Extract text from a document image using AI vision.

    Args:
        file_path: Path to the document image/PDF
        model: Override AI model (default from config)
        max_tokens: Max output tokens
        language_hint: e.g. 'ru', 'fr', 'en' for better accuracy

    Returns:
        Extracted text string, or empty string on failure.
    """
    if not file_path.exists():
        return ""

    config = get_ai_config()
    provider = config.get("provider", "deepseek")
    api_key = config.get("api_key", "") or os.getenv("DEEPSEEK_API_KEY", "")

    if not api_key:
        logger.warning("No API key for external OCR")
        return ""

    if not model:
        model = _best_vision_model(provider, config)

    # Read and encode image
    try:
        image_data = _encode_image(file_path)
        if not image_data:
            return ""
    except Exception as e:
        logger.warning("Failed to read image %s: %s", file_path, e)
        return ""

    # Build prompt
    user_text = "Extract ALL text from this document."
    if language_hint:
        user_text += f" The document is in {language_hint}."

    prompt = OCR_SYSTEM_PROMPT

    # Call provider
    try:
        b64, mime = image_data
        if provider == "deepseek":
            return _call_deepseek_ocr(b64, mime, model, api_key, prompt, user_text, max_tokens)
        else:
            base_url = config.get("base_url", "https://api.openai.com/v1")
            return _call_openai_ocr(b64, mime, model, api_key, base_url, prompt, user_text, max_tokens)
    except Exception as e:
        logger.warning("External OCR failed: %s", e)
        return ""


def _best_vision_model(provider: str, config: dict) -> str:
    """Pick the best available vision-capable model."""
    if config.get("vision_model"):
        return config["vision_model"]
    if provider == "deepseek":
        return "deepseek-chat"  # Supports vision
    return "gpt-4o"


def _encode_image(file_path: Path) -> Optional[tuple[str, str]]:
    """Encode image to base64. Returns (b64_data, mime_type) or None."""
    suffix = file_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
    }

    if suffix == ".pdf":
        # Render first page to image
        try:
            from pdf2image import convert_from_path
            pages = convert_from_path(file_path, first_page=1, last_page=1, dpi=200)
            if not pages:
                return None
            import io
            buf = io.BytesIO()
            pages[0].save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"
        except ImportError:
            logger.warning("pdf2image not available for PDF OCR")
            return None
        except Exception as e:
            logger.warning("PDF render failed: %s", e)
            return None

    if suffix in mime_map:
        try:
            with open(file_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8"), mime_map[suffix]
        except Exception:
            return None

    # Try PIL for other formats
    try:
        from PIL import Image
        import io
        img = Image.open(file_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"
    except Exception:
        return None


def _call_deepseek_ocr(
    b64: str, mime: str, model: str, api_key: str,
    system_prompt: str, user_text: str, max_tokens: int,
) -> str:
    """Call DeepSeek vision API for OCR."""
    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}
                        },
                        {"type": "text", "text": user_text}
                    ]
                }
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    logger.info(
        "External OCR: %d in / %d out tokens (model=%s)",
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        model,
    )
    return text.strip()


def _call_openai_ocr(
    b64: str, mime: str, model: str, api_key: str, base_url: str,
    system_prompt: str, user_text: str, max_tokens: int,
) -> str:
    """Call OpenAI-compatible vision API for OCR."""
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}
                        },
                        {"type": "text", "text": user_text}
                    ]
                }
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return text.strip()


def needs_external_ocr(ocr_text: str, file_path: Path) -> bool:
    """Heuristic: does this document need external OCR?

    Returns True if:
    - Tesseract produced empty text (but file is an image)
    - Tesseract text is very short (< 20 chars for an image)
    - Text looks like garbage (high ratio of non-letter chars)
    """
    if not ocr_text or not ocr_text.strip():
        suffix = file_path.suffix.lower()
        image_exts = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif"}
        if suffix in image_exts:
            return True  # Image with no OCR = likely failed
        return False

    text = ocr_text.strip()

    # Very short result for an image
    suffix = file_path.suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif"}
    if suffix in image_exts and len(text) < 20:
        return True

    # Garbage detection: high ratio of non-letter/non-digit chars
    alpha_num = sum(1 for c in text if c.isalnum() or c.isspace())
    if len(text) > 0 and alpha_num / len(text) < 0.3:
        return True

    return False


# ── Stats tracking ──────────────────────────────────────

_ocr_stats = {
    "total_attempts": 0,
    "successful": 0,
    "failed": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
}


def get_ocr_stats() -> dict:
    """Return external OCR usage statistics."""
    return dict(_ocr_stats)


def reset_ocr_stats():
    """Reset OCR statistics."""
    for key in _ocr_stats:
        _ocr_stats[key] = 0
