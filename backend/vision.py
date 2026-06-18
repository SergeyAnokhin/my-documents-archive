"""AI Vision: visual analysis of document images.

Sends document images to a multimodal AI model (DeepSeek Vision, Gemini, etc.)
to describe what it sees — layout, stamps, tables, handwritten notes.
Useful when OCR alone produces poor results."""

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests

from backend.config import get_ai_config, DB_DIR

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a document analysis assistant. Describe what you see in this document image.
Focus on:
- Document type (invoice, contract, certificate, letter, etc.)
- Key information visible (dates, names, amounts, organizations)
- Document layout and structure
- Whether the document appears official or personal
- Language of the text visible in the image

Respond in the SAME LANGUAGE as the document. If the document is in Russian, respond in Russian.
If French, respond in French. If English, respond in English.

Keep your description concise — 3 to 5 sentences."""


def analyze_image(file_path: Path, filename: str = "") -> str:
    """Send document image to vision model, return description."""
    if not file_path.exists():
        return ""

    config = get_ai_config()
    if not config.get("vision_enabled", False) and not config.get("vision_model"):
        # Auto-enable if a vision model is available
        pass

    provider = config.get("provider", "deepseek")
    vision_model = config.get("vision_model", "")
    api_key = config.get("api_key", "") or os.getenv("DEEPSEEK_API_KEY", "")

    if not api_key:
        logger.warning("No API key for vision analysis")
        return ""

    # Read and encode image
    try:
        with open(file_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.warning("Failed to read image %s: %s", file_path, e)
        return ""

    suffix = file_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
    }
    mime = mime_map.get(suffix, "image/jpeg")

    if provider == "deepseek":
        return _call_deepseek_vision(image_data, mime, vision_model, api_key)
    elif provider == "openai":
        base = config.get("base_url", "https://api.openai.com/v1")
        return _call_openai_vision(image_data, mime, vision_model, api_key, base)
    else:
        # Try OpenAI-compatible
        base = config.get("base_url", "https://api.deepseek.com/v1")
        return _call_openai_vision(image_data, mime, vision_model, api_key, base)


def _call_deepseek_vision(b64: str, mime: str, model: str, api_key: str) -> str:
    """Call DeepSeek vision API."""
    if not model:
        model = "deepseek-chat"  # deepseek-chat supports vision

    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": "Please describe this document."
                        }
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_openai_vision(b64: str, mime: str, model: str, api_key: str, base_url: str) -> str:
    """Call OpenAI-compatible vision API."""
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}
                        },
                        {"type": "text", "text": "Please describe this document."}
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
