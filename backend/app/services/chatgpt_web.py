"""
ChatGPT Web API client — uses session token from browser to access ChatGPT subscription.

Flow:
1. User extracts session token from chatgpt.com browser cookies
2. This module exchanges it for an access token (valid ~1 hour)
3. Access token is used for API calls to chatgpt.com/backend-api/
4. Calls are translated to look like OpenAI API responses for compatibility

Endpoints:
- chatgpt.com/api/auth/session  → session token → access token
- chatgpt.com/backend-api/conversation → chat completions
- chatgpt.com/backend-api/models → list available models
"""
import json
import logging
import time
from typing import Optional
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

# ── Known ChatGPT Web models ────────────────────────────────────────────────
CHATGPT_WEB_MODELS = [
    {"id": "gpt-4.1",        "name": "GPT-4.1",              "vision": True,  "ctx": 1_000_000},
    {"id": "gpt-4.1-mini",   "name": "GPT-4.1 Mini",         "vision": True,  "ctx": 1_000_000},
    {"id": "gpt-4.1-nano",   "name": "GPT-4.1 Nano",         "vision": True,  "ctx": 1_000_000},
    {"id": "gpt-4o",         "name": "GPT-4o",               "vision": True,  "ctx": 128_000},
    {"id": "gpt-4o-mini",    "name": "GPT-4o Mini",          "vision": True,  "ctx": 128_000},
    {"id": "gpt-4.5",        "name": "GPT-4.5",              "vision": True,  "ctx": 128_000},
    {"id": "o3",             "name": "o3",                   "vision": True,  "ctx": 200_000},
    {"id": "o4-mini",        "name": "o4 Mini",              "vision": True,  "ctx": 200_000},
    {"id": "gpt-4",          "name": "GPT-4",                "vision": False, "ctx": 8_000},
    {"id": "o1",             "name": "o1",                   "vision": False, "ctx": 200_000},
    {"id": "o1-mini",        "name": "o1 Mini",              "vision": False, "ctx": 128_000},
    {"id": "o3-mini",        "name": "o3 Mini",              "vision": False, "ctx": 200_000},
]

# ── API endpoints ───────────────────────────────────────────────────────────
CHATGPT_HOST = "https://chatgpt.com"
CHATGPT_ORIGIN = "https://chatgpt.com"

# Approximate pricing per 1M tokens for cost estimation (not actual — subscription is flat-rate)
_WEB_COST_PER_1M_IN = 0.0   # subscription covers it
_WEB_COST_PER_1M_OUT = 0.0


def _browser_headers(access_token: str = "") -> dict:
    """Headers that mimic a browser request to bypass basic Cloudflare checks."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": CHATGPT_ORIGIN,
        "Referer": f"{CHATGPT_ORIGIN}/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


@dataclass
class TokenInfo:
    access_token: str
    expires_at: float  # unix timestamp


# ── Token management ────────────────────────────────────────────────────────

async def get_access_token(session_token: str) -> Optional[str]:
    """Exchange a browser session token for an API access token.

    The session token is stored in the cookie `__Secure-next-auth.session-token`
    on chatgpt.com. This endpoint returns a short-lived access token (JWT).
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{CHATGPT_HOST}/api/auth/session",
                headers={
                    **_browser_headers(),
                    "Cookie": f"__Secure-next-auth.session-token={session_token}",
                },
            )
            if r.status_code != 200:
                log.warning(
                    "ChatGPT Web: session check returned %d — %s",
                    r.status_code, r.text[:200],
                )
                return None

            data = r.json()
            access_token = data.get("accessToken")
            if not access_token:
                log.warning("ChatGPT Web: no accessToken in session response: %s",
                           json.dumps(data)[:300])
                return None

            log.info("ChatGPT Web: got access token (expires: %s)", data.get("expires"))
            return access_token
    except Exception as e:
        log.warning("ChatGPT Web: failed to get access token: %s", e)
        return None


# ── Chat Completions ────────────────────────────────────────────────────────

async def chat_completion(
    session_token: str,
    messages: list[dict],
    model: str = "gpt-4o-mini",
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> tuple[str, int, int, float]:
    """Send messages to ChatGPT Web API and get response text.

    Returns (text, tokens_in, tokens_out, cost).
    """
    access_token = await get_access_token(session_token)
    if not access_token:
        raise RuntimeError("ChatGPT Web: failed to obtain access token — session may be expired")

    # Convert OpenAI format messages to ChatGPT Web format
    chatgpt_messages = _convert_messages(messages)

    body = {
        "action": "next",
        "messages": chatgpt_messages,
        "model": model,
        "parent_message_id": _make_uuid(),
        "conversation_id": None,
        "timezone_offset_min": -180,
        "history_and_training_disabled": False,
        "conversation_mode": {"kind": "primary_assistant"},
        "force_paragen": False,
        "force_rate_limit": False,
    }

    # JSON mode: add system instruction to force JSON output
    if json_mode:
        body["messages"].insert(0, {
            "id": _make_uuid(),
            "author": {"role": "system"},
            "content": {"content_type": "text", "parts": [
                "You MUST respond with valid JSON only. No markdown, no explanation."
            ]},
        })

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{CHATGPT_HOST}/backend-api/conversation",
                headers=_browser_headers(access_token),
                json=body,
            )
            if r.status_code == 429:
                raise RuntimeError("ChatGPT Web: rate limited (429)")
            if r.status_code == 401:
                raise RuntimeError("ChatGPT Web: session expired — please re-login on chatgpt.com")
            if r.status_code != 200:
                raise RuntimeError(
                    f"ChatGPT Web: HTTP {r.status_code}: {r.text[:300]}"
                )

            text = _parse_conversation_response(r.text)
            # Estimate tokens (ChatGPT web doesn't return token counts)
            tokens_in = sum(len(m.get("content", "")) // 4 for m in messages)
            tokens_out = len(text) // 4 if text else 0
            cost = 0.0  # subscription covers it
            return text, tokens_in, tokens_out, cost

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ChatGPT Web: request failed: {e}")


# ── Vision (image → text) ───────────────────────────────────────────────────

async def vision_completion(
    session_token: str,
    image_b64: str,
    prompt: str,
    model: str = "gpt-4o-mini",
    json_mode: bool = False,
) -> tuple[str, int, int, float]:
    """Send image + prompt to ChatGPT Web API for vision analysis."""
    access_token = await get_access_token(session_token)
    if not access_token:
        raise RuntimeError("ChatGPT Web: failed to obtain access token")

    body = {
        "action": "next",
        "messages": [
            {
                "id": _make_uuid(),
                "author": {"role": "user"},
                "content": {
                    "content_type": "multimodal_text",
                    "parts": [
                        prompt,
                        {
                            "content_type": "image_asset_pointer",
                            "asset_pointer": f"data:image/jpeg;base64,{image_b64}",
                            "size_bytes": len(image_b64) * 3 // 4,
                            "width": 1024,
                            "height": 1024,
                        },
                    ],
                },
            }
        ],
        "model": model,
        "parent_message_id": _make_uuid(),
        "conversation_id": None,
        "timezone_offset_min": -180,
        "history_and_training_disabled": False,
        "conversation_mode": {"kind": "primary_assistant"},
        "force_paragen": False,
        "force_rate_limit": False,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{CHATGPT_HOST}/backend-api/conversation",
                headers=_browser_headers(access_token),
                json=body,
            )
            if r.status_code == 429:
                raise RuntimeError("ChatGPT Web: rate limited (429)")
            if r.status_code == 401:
                raise RuntimeError("ChatGPT Web: session expired")
            if r.status_code != 200:
                raise RuntimeError(f"ChatGPT Web: HTTP {r.status_code}: {r.text[:300]}")

            text = _parse_conversation_response(r.text)
            tokens_in = 1000  # rough estimate for vision
            tokens_out = len(text) // 4 if text else 0
            cost = 0.0
            return text, tokens_in, tokens_out, cost

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ChatGPT Web vision: request failed: {e}")


# ── Model listing ───────────────────────────────────────────────────────────

async def list_models(session_token: str) -> list[dict]:
    """Return available models for this ChatGPT subscription from the web API."""
    access_token = await get_access_token(session_token)
    if not access_token:
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{CHATGPT_HOST}/backend-api/models",
                headers=_browser_headers(access_token),
            )
            if r.status_code != 200:
                log.warning("ChatGPT Web models: HTTP %d", r.status_code)
                return _fallback_models()

            data = r.json()
            models = data.get("models") or data
            if not isinstance(models, list):
                return _fallback_models()

            result = []
            for m in models:
                mid = m.get("slug") or m.get("id") or m.get("title", "")
                if not mid:
                    continue
                known = _find_known(mid)
                result.append({
                    "id": mid,
                    "name": m.get("title") or known.get("name", mid),
                    "supports_vision": known.get("vision", _guess_vision(m)),
                    "context_length": known.get("ctx"),
                    "price_in": 0.0,
                    "price_out": 0.0,
                    "is_free": True,  # covered by subscription
                })
            return result if result else _fallback_models()

    except Exception:
        return _fallback_models()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _convert_messages(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format messages to ChatGPT Web API format."""
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal content — extract text
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            content = "\n".join(parts)

        result.append({
            "id": _make_uuid(),
            "author": {"role": role},
            "content": {
                "content_type": "text",
                "parts": [str(content)],
            },
        })
    return result


def _parse_conversation_response(text: str) -> str:
    """Parse ChatGPT Web API response (which may include SSE/streaming wrapper).

    The response is typically plain JSON or a streaming body (text/event-stream).
    We extract the assistant's text content.
    """
    # Try parsing as JSON directly
    try:
        data = json.loads(text)
        # Could be: {"message": {"content": {"parts": [...]}}}
        msg = data.get("message") or data
        parts = msg.get("content", {}).get("parts", [])
        if parts:
            return parts[0] if isinstance(parts[0], str) else str(parts[0])
        return data.get("text", "") or ""
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Try parsing as SSE stream: "data: {...}\n\ndata: {...}\n\ndata: [DONE]\n\n"
    last_text = ""
    for line in text.split("\n"):
        if line.startswith("data: ") and not line.startswith("data: [DONE]"):
            try:
                chunk = json.loads(line[6:])
                parts = (
                    chunk.get("message", {})
                    .get("content", {})
                    .get("parts", [])
                )
                if parts:
                    last_text = "".join(
                        p if isinstance(p, str) else str(p) for p in parts
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    return last_text.strip()


def _make_uuid() -> str:
    """Generate a simple UUID-like ID for messages."""
    import uuid
    return str(uuid.uuid4())


def _find_known(model_id: str) -> dict:
    """Find known model info by ID."""
    for m in CHATGPT_WEB_MODELS:
        if m["id"] == model_id:
            return m
    # Partial match
    for m in CHATGPT_WEB_MODELS:
        if m["id"] in model_id or model_id in m["id"]:
            return m
    return {}


def _guess_vision(model: dict) -> bool:
    """Guess if a model supports vision from its metadata."""
    if "vision" in str(model.get("capabilities", "")).lower():
        return True
    if model.get("supports_vision") or model.get("vision_enabled"):
        return True
    # Most modern ChatGPT models support vision
    slug = (model.get("slug") or model.get("id") or "").lower()
    if any(k in slug for k in ("gpt-4o", "gpt-4.1", "gpt-4.5", "o3", "o4")):
        return True
    return False


def _fallback_models() -> list[dict]:
    """Return hardcoded model list when the API is unavailable."""
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "supports_vision": m["vision"],
            "context_length": m["ctx"],
            "price_in": 0.0,
            "price_out": 0.0,
            "is_free": True,
        }
        for m in CHATGPT_WEB_MODELS
    ]
