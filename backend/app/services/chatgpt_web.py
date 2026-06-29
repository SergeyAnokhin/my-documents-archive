"""
ChatGPT OAuth 2.0 client — Device Code flow for ChatGPT subscription.

Flow (same as Hermes Agent / OpenAI Codex):
1. App calls start_device_flow() → gets user_code + verification_uri
2. User visits chatgpt.com/device and enters the 8-digit code
3. App polls poll_for_token() → gets access_token + refresh_token
4. Tokens stored; access_token used for API calls
5. When access_token expires, refresh_oauth_token() uses refresh_token

Key constants from Hermes Agent:
  CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
  CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"

API endpoint: chatgpt.com/backend-api/conversation (the ChatGPT web API)
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ── OAuth constants (from Hermes Agent) ─────────────────────────────────────
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_DEVICE_CODE_URL = "https://auth.openai.com/oauth/device/code"
DEFAULT_SCOPE = "offline_access openid profile email"

# ── API endpoints ───────────────────────────────────────────────────────────
CHATGPT_HOST = "https://chatgpt.com"

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


# ═══════════════════════════════════════════════════════════════════════════════
# OAuth 2.0 Device Code Flow
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str            # 8-character code the user enters
    verification_uri: str     # URL the user visits (e.g. https://chatgpt.com/device)
    verification_uri_complete: str = ""  # URL with user_code pre-filled
    expires_in: int = 900     # seconds until device_code expires
    interval: int = 5         # seconds between poll attempts


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    # Computed client-side
    expires_at: float = 0.0  # unix timestamp


async def start_device_flow() -> DeviceCodeResponse:
    """Initiate OAuth 2.0 Device Authorization flow.

    Returns the user_code and verification_uri to show to the user.
    The user must visit the URL and enter the code to authorize.

    Raises RuntimeError on network/auth failures.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                CODEX_DEVICE_CODE_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "scope": DEFAULT_SCOPE,
                },
            )

        if r.status_code == 429:
            raise RuntimeError(
                "ChatGPT OAuth: rate limited (429) — too many device code "
                "requests. Wait a minute and try again."
            )
        if r.status_code != 200:
            body = r.text[:300]
            raise RuntimeError(
                f"ChatGPT OAuth: device code request failed "
                f"(HTTP {r.status_code}): {body}"
            )

        data = r.json()
        result = DeviceCodeResponse(
            device_code=data["device_code"],
            user_code=data.get("user_code", ""),
            verification_uri=data.get("verification_uri", "https://chatgpt.com/device"),
            verification_uri_complete=data.get("verification_uri_complete", ""),
            expires_in=int(data.get("expires_in", 900)),
            interval=int(data.get("interval", 5)),
        )
        log.info(
            "ChatGPT OAuth: device code ready — user_code=%s, expires_in=%ds",
            result.user_code, result.expires_in,
        )
        return result

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ChatGPT OAuth: device code request failed: {e}")


async def poll_for_token(device_code: str) -> TokenResponse:
    """Poll the token endpoint until the user authorizes.

    Returns TokenResponse on success.
    Raises RuntimeError with specific messages for pending/expired/denied states.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                CODEX_OAUTH_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                },
            )

        if r.status_code == 200:
            data = r.json()
            expires_in = int(data.get("expires_in", 3600))
            result = TokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", ""),
                token_type=data.get("token_type", "Bearer"),
                expires_in=expires_in,
                expires_at=time.time() + expires_in - 120,  # refresh 2 min before expiry
            )
            log.info("ChatGPT OAuth: token obtained (expires in %ds)", expires_in)
            return result

        # Non-200: check error type
        try:
            err = r.json()
        except Exception:
            err = {}

        error = ""
        if isinstance(err, dict):
            error = err.get("error", "")
            if isinstance(error, dict):
                error = error.get("code", "") or error.get("type", "")
            error = str(error).strip()

        if error == "authorization_pending":
            raise RuntimeError("authorization_pending")
        if error == "slow_down":
            raise RuntimeError("slow_down")
        if error in ("access_denied", "authorization_declined"):
            raise RuntimeError(
                "ChatGPT OAuth: authorization was declined by user. "
                "Please try again."
            )
        if error == "expired_token":
            raise RuntimeError(
                "ChatGPT OAuth: device code expired. "
                "Please start a new authorization flow."
            )
        if r.status_code == 429:
            raise RuntimeError(
                "ChatGPT OAuth: rate limited (429). Wait and try again."
            )

        raise RuntimeError(
            f"ChatGPT OAuth: token request failed "
            f"(HTTP {r.status_code}, error={error or 'unknown'}): "
            f"{r.text[:200]}"
        )

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ChatGPT OAuth: token poll failed: {e}")


async def refresh_oauth_token(refresh_token: str) -> TokenResponse:
    """Refresh an expired OAuth access token using the refresh_token.

    Returns a new TokenResponse with fresh tokens.
    Raises RuntimeError if the refresh_token is invalid/expired.
    """
    if not refresh_token:
        raise RuntimeError(
            "ChatGPT OAuth: missing refresh_token. Re-authentication required."
        )

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                CODEX_OAUTH_TOKEN_URL,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                },
            )

        if r.status_code == 429:
            raise RuntimeError(
                "ChatGPT OAuth: rate limited on token refresh (429). "
                "Credentials still valid; retry later."
            )

        if r.status_code != 200:
            try:
                err = r.json()
            except Exception:
                err = {}
            error = ""
            if isinstance(err, dict):
                err_obj = err.get("error")
                if isinstance(err_obj, dict):
                    error = err_obj.get("code", "") or err_obj.get("type", "")
                elif isinstance(err_obj, str):
                    error = err_obj
                else:
                    error = str(err_obj or "")

            if error in ("invalid_grant", "invalid_token", "invalid_request",
                         "refresh_token_reused"):
                raise RuntimeError(
                    "ChatGPT OAuth: refresh token invalid/consumed. "
                    "Re-authentication required."
                )
            if r.status_code in (401, 403):
                raise RuntimeError(
                    "ChatGPT OAuth: refresh token rejected (401/403). "
                    "Re-authentication required."
                )
            raise RuntimeError(
                f"ChatGPT OAuth: token refresh failed "
                f"(HTTP {r.status_code}): {r.text[:200]}"
            )

        data = r.json()
        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError(
                "ChatGPT OAuth: refresh response missing access_token. "
                "Re-authentication required."
            )

        new_refresh = data.get("refresh_token", "") or refresh_token
        expires_in = int(data.get("expires_in", 3600))
        result = TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh,
            token_type=data.get("token_type", "Bearer"),
            expires_in=expires_in,
            expires_at=time.time() + expires_in - 120,
        )
        log.info("ChatGPT OAuth: token refreshed (expires in %ds)", expires_in)
        return result

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ChatGPT OAuth: token refresh failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# API Calls (using OAuth access token)
# ═══════════════════════════════════════════════════════════════════════════════

def _browser_headers(access_token: str = "") -> dict:
    """Headers that mimic a browser request to bypass basic Cloudflare checks."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": CHATGPT_HOST,
        "Referer": f"{CHATGPT_HOST}/",
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


async def chat_completion(
    access_token: str,
    messages: list[dict],
    model: str = "gpt-4o-mini",
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> tuple[str, int, int, float]:
    """Send messages to ChatGPT Web API using OAuth access token.

    Returns (text, tokens_in, tokens_out, cost).
    """
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
                raise RuntimeError("ChatGPT: rate limited (429)")
            if r.status_code == 401:
                raise RuntimeError(
                    "ChatGPT: access token expired or invalid (401). "
                    "Token refresh needed."
                )
            if r.status_code != 200:
                raise RuntimeError(f"ChatGPT: HTTP {r.status_code}: {r.text[:300]}")

            text = _parse_conversation_response(r.text)
            tokens_in = sum(len(m.get("content", "")) // 4 for m in messages)
            tokens_out = len(text) // 4 if text else 0
            cost = 0.0  # subscription covers it
            return text, tokens_in, tokens_out, cost

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ChatGPT: request failed: {e}")


async def vision_completion(
    access_token: str,
    image_b64: str,
    prompt: str,
    model: str = "gpt-4o-mini",
    json_mode: bool = False,
) -> tuple[str, int, int, float]:
    """Send image + prompt to ChatGPT Web API for vision analysis using OAuth access token."""
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
                raise RuntimeError("ChatGPT: rate limited (429)")
            if r.status_code == 401:
                raise RuntimeError(
                    "ChatGPT: access token expired or invalid (401). "
                    "Token refresh needed."
                )
            if r.status_code != 200:
                raise RuntimeError(f"ChatGPT: HTTP {r.status_code}: {r.text[:300]}")

            text = _parse_conversation_response(r.text)
            tokens_in = 1000
            tokens_out = len(text) // 4 if text else 0
            cost = 0.0
            return text, tokens_in, tokens_out, cost

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ChatGPT vision: request failed: {e}")


async def list_models(access_token: str) -> list[dict]:
    """Return available models for this ChatGPT subscription."""
    if not access_token:
        return _fallback_models()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{CHATGPT_HOST}/backend-api/models",
                headers=_browser_headers(access_token),
            )
            if r.status_code != 200:
                log.warning("ChatGPT models: HTTP %d", r.status_code)
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
                    "is_free": True,
                })
            return result if result else _fallback_models()

    except Exception:
        return _fallback_models()


# ═══════════════════════════════════════════════════════════════════════════════
# Token lifecycle helpers for AIAnalysis/AIVision callers
# ═══════════════════════════════════════════════════════════════════════════════

def _oauth_extra_fields(provider) -> dict:
    """Extract OAuth fields from an AIProvider's extra_params dict."""
    extra = getattr(provider, "extra_params", None) or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    return extra.get("oauth", {}) if isinstance(extra, dict) else {}


async def ensure_fresh_token(provider, db_session=None) -> str:
    """Ensure provider has a valid OAuth access token, refreshing if needed.

    Returns the current valid access_token.
    Raises RuntimeError if token is missing and cannot be refreshed.
    """
    oauth = _oauth_extra_fields(provider)
    access_token = provider.api_key
    expires_at = oauth.get("expires_at", 0)
    refresh_token = oauth.get("refresh_token", "")

    # Token is still fresh
    if access_token and expires_at > time.time():
        return access_token

    # Token expired — try to refresh
    if refresh_token:
        log.info("ChatGPT OAuth: access token expired, refreshing...")
        try:
            new_tokens = await refresh_oauth_token(refresh_token)
            # Update provider in DB
            provider.api_key = new_tokens.access_token
            extra = getattr(provider, "extra_params", None) or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            extra["oauth"] = {
                "refresh_token": new_tokens.refresh_token,
                "expires_at": new_tokens.expires_at,
                "token_type": new_tokens.token_type,
            }
            provider.extra_params = extra

            if db_session:
                db_session.commit()
                db_session.refresh(provider)

            log.info("ChatGPT OAuth: token refreshed successfully")
            return new_tokens.access_token
        except Exception as e:
            log.warning("ChatGPT OAuth: token refresh failed: %s", e)
            # If we have an old token, try it anyway (might still work)
            if access_token:
                return access_token
            raise

    # No refresh token, no access token
    if access_token:
        return access_token  # return whatever we have
    raise RuntimeError(
        "ChatGPT OAuth: no access token and no refresh token. "
        "Re-authentication required."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers (unchanged from chatgpt_web.py)
# ═══════════════════════════════════════════════════════════════════════════════

def _convert_messages(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format messages to ChatGPT Web API format."""
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
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
    """Parse ChatGPT Web API response."""
    try:
        data = json.loads(text)
        msg = data.get("message") or data
        parts = msg.get("content", {}).get("parts", [])
        if parts:
            return parts[0] if isinstance(parts[0], str) else str(parts[0])
        return data.get("text", "") or ""
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

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
    import uuid
    return str(uuid.uuid4())


def _find_known(model_id: str) -> dict:
    for m in CHATGPT_WEB_MODELS:
        if m["id"] == model_id:
            return m
    for m in CHATGPT_WEB_MODELS:
        if m["id"] in model_id or model_id in m["id"]:
            return m
    return {}


def _guess_vision(model: dict) -> bool:
    if "vision" in str(model.get("capabilities", "")).lower():
        return True
    if model.get("supports_vision") or model.get("vision_enabled"):
        return True
    slug = (model.get("slug") or model.get("id") or "").lower()
    if any(k in slug for k in ("gpt-4o", "gpt-4.1", "gpt-4.5", "o3", "o4")):
        return True
    return False


def _fallback_models() -> list[dict]:
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
