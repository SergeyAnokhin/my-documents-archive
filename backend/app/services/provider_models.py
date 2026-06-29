"""Fetch available model lists from AI provider APIs.

Returns a list of dicts with: id, name, supports_vision, context_length, price_in, price_out.
Price is in USD per 1M tokens (approximate; verify with provider docs).
"""
import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# Known pricing per 1M tokens (in, out) and capabilities
# Prices approximate as of Q2 2025 — check provider docs for current rates
KNOWN_MODELS: dict[str, dict] = {
    # OpenAI
    "gpt-4o-mini":                {"name": "GPT-4o mini",              "in": 0.15,   "out": 0.60,  "vision": True,  "ctx": 128_000},
    "gpt-4o":                     {"name": "GPT-4o",                   "in": 2.50,   "out": 10.0,  "vision": True,  "ctx": 128_000},
    "gpt-4-turbo":                {"name": "GPT-4 Turbo",              "in": 10.0,   "out": 30.0,  "vision": True,  "ctx": 128_000},
    "gpt-3.5-turbo":              {"name": "GPT-3.5 Turbo",            "in": 0.50,   "out": 1.50,  "vision": False, "ctx": 16_000},
    "o1-mini":                    {"name": "o1 mini",                  "in": 3.0,    "out": 12.0,  "vision": False, "ctx": 128_000},
    "o3-mini":                    {"name": "o3 mini",                  "in": 1.10,   "out": 4.40,  "vision": False, "ctx": 200_000},
    # Google Gemini
    "gemini-2.0-flash":               {"name": "Gemini 2.0 Flash",         "in": 0.10,   "out": 0.40,  "vision": True,  "ctx": 1_000_000},
    "gemini-2.0-flash-lite":          {"name": "Gemini 2.0 Flash Lite",    "in": 0.075,  "out": 0.30,  "vision": True,  "ctx": 1_000_000},
    "gemini-2.0-flash-exp":           {"name": "Gemini 2.0 Flash Exp",     "in": 0.10,   "out": 0.40,  "vision": True,  "ctx": 1_000_000},
    "gemini-1.5-flash":               {"name": "Gemini 1.5 Flash",         "in": 0.075,  "out": 0.30,  "vision": True,  "ctx": 1_000_000},
    "gemini-1.5-flash-8b":            {"name": "Gemini 1.5 Flash 8B",      "in": 0.0375, "out": 0.15,  "vision": True,  "ctx": 1_000_000},
    "gemini-1.5-flash-002":           {"name": "Gemini 1.5 Flash 002",     "in": 0.075,  "out": 0.30,  "vision": True,  "ctx": 1_000_000},
    "gemini-1.5-pro":                 {"name": "Gemini 1.5 Pro",           "in": 3.50,   "out": 10.50, "vision": True,  "ctx": 2_000_000},
    "gemini-1.5-pro-002":             {"name": "Gemini 1.5 Pro 002",       "in": 3.50,   "out": 10.50, "vision": True,  "ctx": 2_000_000},
    "gemini-2.5-flash":               {"name": "Gemini 2.5 Flash",         "in": 0.15,   "out": 0.60,  "vision": True,  "ctx": 1_000_000},
    "gemini-2.5-flash-lite":          {"name": "Gemini 2.5 Flash Lite",    "in": 0.10,   "out": 0.40,  "vision": True,  "ctx": 1_000_000},
    "gemini-2.5-pro":                 {"name": "Gemini 2.5 Pro",           "in": 1.25,   "out": 10.0,  "vision": True,  "ctx": 2_000_000},
    "gemini-2.5-flash-preview-05-20": {"name": "Gemini 2.5 Flash Preview", "in": 0.15,   "out": 0.60,  "vision": True,  "ctx": 1_000_000},
    "gemini-2.5-pro-preview-06-05":   {"name": "Gemini 2.5 Pro Preview",   "in": 1.25,   "out": 10.0,  "vision": True,  "ctx": 2_000_000},
    # Gemini 3.x preview models
    "gemini-3.0-flash":               {"name": "Gemini 3.0 Flash",         "in": 0.10,   "out": 0.40,  "vision": True,  "ctx": 1_000_000},
    "gemini-3.1-flash-lite-preview":  {"name": "Gemini 3.1 Flash Lite",    "in": 0.075,  "out": 0.30,  "vision": True,  "ctx": 1_000_000},
    "gemini-3.1-flash-preview":       {"name": "Gemini 3.1 Flash",         "in": 0.10,   "out": 0.40,  "vision": True,  "ctx": 1_000_000},
    # Mistral (text models)
    "mistral-large-latest":     {"name": "Mistral Large",    "in": 2.0,  "out": 6.0,  "vision": False, "ctx": 131_000},
    "mistral-medium-latest":    {"name": "Mistral Medium",   "in": 0.40, "out": 2.0,  "vision": False, "ctx": 131_000},
    "mistral-small-latest":     {"name": "Mistral Small",    "in": 0.10, "out": 0.30, "vision": False, "ctx": 131_000},
    "mistral-nemo":             {"name": "Mistral Nemo",     "in": 0.15, "out": 0.15, "vision": False, "ctx": 131_000},
    "open-mistral-nemo":        {"name": "Open Mistral Nemo","in": 0.15, "out": 0.15, "vision": False, "ctx": 131_000},
    "open-mistral-7b":          {"name": "Open Mistral 7B",  "in": 0.25, "out": 0.25, "vision": False, "ctx": 32_000},
    "open-mixtral-8x7b":        {"name": "Mixtral 8x7B",     "in": 0.70, "out": 0.70, "vision": False, "ctx": 32_000},
    "pixtral-large-latest":     {"name": "Pixtral Large",    "in": 2.0,  "out": 6.0,  "vision": True,  "ctx": 131_000},
    "pixtral-12b-2409":         {"name": "Pixtral 12B",      "in": 0.15, "out": 0.15, "vision": True,  "ctx": 131_000},
    # DeepSeek
    "deepseek-chat":              {"name": "DeepSeek Chat (V3)",        "in": 0.07,   "out": 1.10,  "vision": False, "ctx": 64_000},
    "deepseek-reasoner":          {"name": "DeepSeek Reasoner (R1)",    "in": 0.55,   "out": 2.19,  "vision": False, "ctx": 64_000},
}

# OpenAI models to show (filter out embeddings, TTS, image-gen, etc.)
_OPENAI_TEXT_MODELS = [
    "gpt-4o-mini", "gpt-4o", "o3-mini", "o1-mini", "gpt-4-turbo", "gpt-3.5-turbo",
]

# Gemini model ID prefixes that are no longer available for inference.
# Google keeps these in the /v1beta/models list but returns 404 on generate_content.
_GEMINI_DEPRECATED_PREFIXES = (
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-exp",
)


def _is_gemini_deprecated(model_id: str) -> bool:
    return any(
        model_id == p or model_id.startswith(p + "-")
        for p in _GEMINI_DEPRECATED_PREFIXES
    )


def _gemini_infer_pricing(model_id: str) -> dict:
    """Infer approximate pricing for unknown Gemini models by name pattern."""
    mid = model_id.lower()
    # Open-source Gemma models are free through AI Studio
    if "gemma" in mid:
        return {"in": 0.0, "out": 0.0, "vision": False}
    # Pro-tier: pro models, deep research, robotics, ultra
    if any(k in mid for k in ("pro", "research", "robotics", "ultra")):
        return {"in": 1.25, "out": 10.0, "vision": True}
    # Flash-lite tier: lite variants, nano, clip (music/multimodal)
    if any(k in mid for k in ("flash-lite", "flash-8b", "nano", "clip")):
        return {"in": 0.075, "out": 0.30, "vision": True}
    # Flash tier: flash, computer-use (flash-based), other experimental
    if any(k in mid for k in ("flash", "computer-use")):
        return {"in": 0.10, "out": 0.40, "vision": True}
    # Unknown Gemini model: flash-tier as conservative estimate
    return {"in": 0.10, "out": 0.40, "vision": True}


def _enrich(model_id: str, display_name: str = "", provider_type: str = "") -> dict:
    info = KNOWN_MODELS.get(model_id, {})
    if not info and provider_type == "gemini":
        info = _gemini_infer_pricing(model_id)
    return {
        "id": model_id,
        "name": info.get("name") or display_name or model_id,
        "supports_vision": info.get("vision", False),
        "context_length": info.get("ctx"),
        "price_in": info.get("in"),
        "price_out": info.get("out"),
        "is_free": info.get("in") == 0.0,
    }


async def fetch_models(
    provider_type: str,
    api_key: str,
    base_url: Optional[str] = None,
) -> list[dict]:
    """Return list of available models for this provider. Never raises — returns [] on error."""
    try:
        if provider_type == "openrouter":
            return await _fetch_openrouter(api_key)
        if provider_type == "gemini":
            return await _fetch_gemini(api_key)
        if provider_type == "mistral":
            return await _fetch_mistral(api_key)
        if provider_type == "deepseek":
            url = base_url or "https://api.deepseek.com/v1"
            return await _fetch_openai_compat(api_key, url, provider_type)
        if provider_type == "openai":
            url = base_url or "https://api.openai.com/v1"
            return await _fetch_openai_compat(api_key, url, provider_type)
        if provider_type == "openai_web":
            return await _fetch_chatgpt_web(api_key)
    except Exception as e:
        log.warning("fetch_models(%s) failed: %s", provider_type, e)
    return []


_MISTRAL_OCR_MODEL = {
    "id": "mistral-ocr-latest",
    "name": "Mistral OCR",
    "supports_vision": True,
    "context_length": None,
    "price_in": None,
    "price_out": None,
    "is_free": False,
}

_MISTRAL_TEXT_IDS = [
    "mistral-large-latest", "mistral-medium-latest", "mistral-small-latest",
    "open-mistral-nemo", "pixtral-large-latest", "pixtral-12b-2409",
]


def _mistral_ocr_models() -> list[dict]:
    """Static Mistral model list (OCR + known text models). No API call."""
    return [_MISTRAL_OCR_MODEL] + [_enrich(mid) for mid in _MISTRAL_TEXT_IDS]


async def _fetch_mistral(api_key: str) -> list[dict]:
    """Fetch Mistral models via API; fall back to static list."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
        ids = {m["id"] for m in r.json().get("data", [])}
        result = [_MISTRAL_OCR_MODEL]
        for mid in _MISTRAL_TEXT_IDS:
            if mid in ids:
                result.append(_enrich(mid))
        already = {m["id"] for m in result}
        for mid in sorted(ids):
            if mid not in already and mid not in ("mistral-embed", "mistral-moderation-latest"):
                result.append(_enrich(mid, provider_type="mistral"))
        return result
    except Exception:
        return _mistral_ocr_models()


async def _fetch_openai_compat(api_key: str, base_url: str, provider_type: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        r.raise_for_status()
    all_ids = {m["id"] for m in r.json().get("data", [])}

    if provider_type == "openai":
        return [_enrich(mid) for mid in _OPENAI_TEXT_MODELS if mid in all_ids]

    # DeepSeek and other OpenAI-compatible: prefer known models, fall back to all
    known = [mid for mid in KNOWN_MODELS if mid in all_ids]
    if known:
        return [_enrich(mid) for mid in known]
    return [_enrich(m) for m in sorted(all_ids)]


async def _fetch_gemini(api_key: str) -> list[dict]:
    import re as _re
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
        )
        r.raise_for_status()

    result = []
    for m in r.json().get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        raw_id = m.get("name", "")
        model_id = raw_id.removeprefix("models/")
        if _is_gemini_deprecated(model_id):
            continue
        item = _enrich(model_id, m.get("displayName", ""), "gemini")
        if item["context_length"] is None:
            item["context_length"] = m.get("inputTokenLimit")
        # All Gemini models that support generateContent also support vision (multimodal)
        item["supports_vision"] = True
        result.append(item)

    # Drop versioned snapshots (e.g. gemini-2.0-flash-lite-001) when the stable
    # alias (gemini-2.0-flash-lite) is also present — Google keeps deprecated
    # snapshots in the list but they return 404 on inference.
    stable_ids = {item["id"] for item in result}
    _versioned = _re.compile(r"^(.*)-(\d{3})$")
    result = [
        item for item in result
        if not (m := _versioned.match(item["id"])) or m.group(1) not in stable_ids
    ]

    # Known models (with pricing) first, then unknown sorted by id
    result.sort(key=lambda x: (x["price_in"] is None, x["id"]))
    return result


async def _fetch_openrouter(api_key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        r.raise_for_status()

    result = []
    for m in r.json().get("data", []):
        pricing = m.get("pricing", {})
        try:
            raw_in  = float(pricing.get("prompt", 0) or 0)
            raw_out = float(pricing.get("completion", 0) or 0)
            # Clamp negatives (OpenRouter uses -1 as sentinel for some pricing models)
            price_in  = max(0.0, raw_in)  * 1_000_000
            price_out = max(0.0, raw_out) * 1_000_000
        except (ValueError, TypeError):
            price_in = price_out = None

        # OpenRouter free models: pricing.prompt == "0"
        is_free = (price_in is not None and price_in == 0.0)

        modality = m.get("architecture", {}).get("modality", "")
        result.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "supports_vision": "image" in modality,
            "context_length": m.get("context_length"),
            "price_in":  price_in  if price_in  else None,
            "price_out": price_out if price_out else None,
            "is_free": is_free,
        })

    # Free first, then cheapest
    result.sort(key=lambda x: (not x["is_free"], x["price_in"] or 0))
    return result


async def _fetch_chatgpt_web(session_token: str) -> list[dict]:
    """Fetch available Codex model IDs from ChatGPT backend.

    Tries the live API first: chatgpt.com/backend-api/codex/models
    Falls back to hardcoded DEFAULT_CODEX_MODELS (same as Hermes Agent).
    """
    import httpx
    
    # Try live API
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://chatgpt.com/backend-api/codex/models?client_version=1.0.0",
                headers={"Authorization": f"Bearer {session_token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                entries = data.get("models", []) if isinstance(data, dict) else []
                if entries:
                    sortable = []
                    for item in entries:
                        if not isinstance(item, dict):
                            continue
                        slug = item.get("slug")
                        if not isinstance(slug, str) or not slug.strip():
                            continue
                        visibility = item.get("visibility", "")
                        if isinstance(visibility, str) and visibility.strip().lower() in {"hide", "hidden"}:
                            continue
                        priority = item.get("priority")
                        rank = int(priority) if isinstance(priority, (int, float)) else 10_000
                        sortable.append((rank, slug))
                    sortable.sort(key=lambda x: (x[0], x[1]))
                    api_models = [slug for _, slug in sortable]
                    if api_models:
                        return [
                            {"id": mid, "name": _codex_display_name(mid),
                             "supports_vision": _codex_supports_vision(mid),
                             "context_length": _codex_context(mid),
                             "price_in": 0.0, "price_out": 0.0, "is_free": True}
                            for mid in api_models
                        ]
    except Exception:
        pass  # fall through to hardcoded list

    # Fallback: hardcoded Codex models (same as Hermes Agent codex_models.py)
    from .chatgpt_web import DEFAULT_CODEX_MODELS
    return [
        {
            "id": mid,
            "name": _codex_display_name(mid),
            "supports_vision": _codex_supports_vision(mid),
            "context_length": _codex_context(mid),
            "price_in": 0.0,
            "price_out": 0.0,
            "is_free": True,
        }
        for mid in DEFAULT_CODEX_MODELS
    ]


def _codex_display_name(model_id: str) -> str:
    names = {
        "gpt-5.5": "GPT-5.5",
        "gpt-5.5-pro": "GPT-5.5 Pro",
        "gpt-5.4": "GPT-5.4",
        "gpt-5.4-mini": "GPT-5.4 Mini",
        "gpt-5.4-nano": "GPT-5.4 Nano",
        "gpt-5.3-codex": "GPT-5.3 Codex",
        "gpt-5.3-codex-spark": "GPT-5.3 Codex Spark",
        "gpt-5.2-codex": "GPT-5.2 Codex",
        "gpt-5.1-codex-max": "GPT-5.1 Codex Max",
        "gpt-5.1-codex-mini": "GPT-5.1 Codex Mini",
        "gpt-5-codex": "GPT-5 Codex",
        "gpt-5-mini": "GPT-5 Mini",
        "gpt-5-nano": "GPT-5 Nano",
    }
    return names.get(model_id, model_id)


def _codex_supports_vision(model_id: str) -> bool:
    # All GPT-5.x models support vision
    return True


def _codex_context(model_id: str) -> int:
    # Codex backend caps context at 272K for most GPT-5.x models
    small = {"gpt-5.3-codex-spark", "gpt-5.1-codex-mini"}
    if model_id in small:
        return 128_000
    if model_id in {"gpt-5.5", "gpt-5.5-pro", "gpt-5.4", "gpt-5.4-mini",
                    "gpt-5.4-nano", "gpt-5.3-codex", "gpt-5.2-codex",
                    "gpt-5.1-codex-max", "gpt-5-codex", "gpt-5-mini", "gpt-5-nano"}:
        return 272_000
    return 128_000
