"""
ChatGPT OAuth client — OpenAI's proprietary Device Auth flow.

EXACT endpoints reverse-engineered from Hermes Agent (hermes_cli/auth.py):
  1. POST auth.openai.com/api/accounts/deviceauth/usercode → {user_code, device_auth_id}
  2. User visits auth.openai.com/codex/device and enters the code
  3. POST auth.openai.com/api/accounts/deviceauth/token → {authorization_code, code_verifier}
  4. POST auth.openai.com/oauth/token (grant_type=authorization_code) → {access_token, refresh_token}
  
Token refresh:
  POST auth.openai.com/oauth/token (grant_type=refresh_token) → new tokens

API inference:
  chatgpt.com/backend-api/conversation using Bearer access_token
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ── Constants (from Hermes Agent) ────────────────────────────────────────────
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_OAUTH_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/oauth/token"

# OpenAI's proprietary device-auth endpoints (NOT standard OAuth device code!)
DEVICE_AUTH_USERCODE_URL = f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/usercode"
DEVICE_AUTH_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/token"
DEVICE_VERIFICATION_URL = f"{CODEX_OAUTH_ISSUER}/codex/device"
DEVICE_CALLBACK_URL = f"{CODEX_OAUTH_ISSUER}/deviceauth/callback"

# ── API endpoints ───────────────────────────────────────────────────────────
CHATGPT_HOST = "https://chatgpt.com"

# ── Known ChatGPT Web models ────────────────────────────────────────────────

# Default Codex models — same as Hermes Agent (hermes_cli/codex_models.py)
DEFAULT_CODEX_MODELS = [
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
]

# Legacy list (kept for backward compat, unused by provider_models)
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
# OpenAI Proprietary Device Auth Flow
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DeviceCodeResponse:
    device_auth_id: str
    user_code: str             # 8-character code the user enters
    verification_uri: str      # auth.openai.com/codex/device
    interval: int = 5          # seconds between poll attempts
    expires_in: int = 900


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    expires_at: float = 0.0


async def start_device_flow() -> DeviceCodeResponse:
    """Step 1: Request device auth user code from OpenAI.

    Calls the proprietary endpoint used by ChatGPT desktop apps.
    """
    max_attempts = 4
    resp = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    DEVICE_AUTH_USERCODE_URL,
                    json={"client_id": CODEX_OAUTH_CLIENT_ID},
                    headers={"Content-Type": "application/json"},
                )
        except Exception as exc:
            raise RuntimeError(f"ChatGPT OAuth: device code request failed: {exc}")

        if resp.status_code != 429:
            break
        if attempt < max_attempts:
            delay = min(2 ** attempt, 60)
            await _async_sleep(delay)

    if resp is None or (resp.status_code == 429):
        raise RuntimeError(
            "ChatGPT OAuth: rate limited (429). Wait a minute and try again."
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"ChatGPT OAuth: device code request failed "
            f"(HTTP {resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json()
    user_code = data.get("user_code", "")
    device_auth_id = data.get("device_auth_id", "")
    interval = max(3, int(data.get("interval", 5)))

    if not user_code or not device_auth_id:
        raise RuntimeError("ChatGPT OAuth: incomplete device code response")

    log.info("ChatGPT OAuth: device_auth_id=%s user_code=%s", device_auth_id[:8], user_code)
    return DeviceCodeResponse(
        device_auth_id=device_auth_id,
        user_code=user_code,
        verification_uri=DEVICE_VERIFICATION_URL,
        interval=interval,
    )


async def poll_for_token(device_auth_id: str, user_code: str, interval: int) -> TokenResponse:
    """Step 2-4: Poll for authorization, then exchange code for tokens.

    First polls the proprietary token endpoint until user authorizes,
    then exchanges the authorization_code for OAuth tokens.
    """
    # ── Poll for authorization code ──────────────────────────────────────
    authorization_code = ""
    code_verifier = ""
    max_wait = 15 * 60
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=15.0) as client:
        while time.monotonic() - start < max_wait:
            await _async_sleep(interval)
            try:
                poll_resp = await client.post(
                    DEVICE_AUTH_TOKEN_URL,
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
            except Exception:
                continue

            if poll_resp.status_code == 200:
                data = poll_resp.json()
                authorization_code = data.get("authorization_code", "")
                code_verifier = data.get("code_verifier", "")
                if authorization_code and code_verifier:
                    break
                raise RuntimeError("ChatGPT OAuth: incomplete authorization response")
            elif poll_resp.status_code in {403, 404}:
                continue  # user hasn't authorized yet
            elif poll_resp.status_code == 400:
                # May mean expired
                raise RuntimeError("authorization_pending")
            else:
                raise RuntimeError(
                    f"ChatGPT OAuth: poll error HTTP {poll_resp.status_code}"
                )

    if not authorization_code:
        raise RuntimeError("authorization_pending")  # still pending (caller retries)

    # ── Exchange authorization code for OAuth tokens ─────────────────────
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": DEVICE_CALLBACK_URL,
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        raise RuntimeError(f"ChatGPT OAuth: token exchange failed: {exc}")

    if token_resp.status_code == 429:
        raise RuntimeError("ChatGPT OAuth: rate limited on token exchange (429)")

    if token_resp.status_code != 200:
        raise RuntimeError(
            f"ChatGPT OAuth: token exchange failed "
            f"(HTTP {token_resp.status_code}): {token_resp.text[:300]}"
        )

    data = token_resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token", "")

    if not access_token:
        raise RuntimeError("ChatGPT OAuth: token response missing access_token")

    expires_in = int(data.get("expires_in", 3600))
    result = TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type=data.get("token_type", "Bearer"),
        expires_in=expires_in,
        expires_at=time.time() + expires_in - 120,
    )
    log.info("ChatGPT OAuth: tokens obtained (expires in %ds)", expires_in)
    return result


async def refresh_oauth_token(refresh_token: str) -> TokenResponse:
    """Refresh an expired OAuth access token."""
    if not refresh_token:
        raise RuntimeError("ChatGPT OAuth: missing refresh_token")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
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
            raise RuntimeError("ChatGPT OAuth: rate limited on refresh (429)")

        if r.status_code != 200:
            # Check for invalid_grant → re-auth needed
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

            if error in ("invalid_grant", "invalid_token", "refresh_token_reused"):
                raise RuntimeError("ChatGPT OAuth: refresh token invalid — re-auth required")
            if r.status_code in (401, 403):
                raise RuntimeError("ChatGPT OAuth: refresh rejected — re-auth required")
            raise RuntimeError(
                f"ChatGPT OAuth: refresh failed HTTP {r.status_code}: {r.text[:200]}"
            )

        data = r.json()
        access_token = data.get("access_token")
        if not access_token:
            raise RuntimeError("ChatGPT OAuth: refresh response missing access_token")

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
        raise RuntimeError(f"ChatGPT OAuth: refresh failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# API Calls (using OAuth access token)
# ═══════════════════════════════════════════════════════════════════════════════

def _browser_headers(access_token: str = "") -> dict:
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
                raise RuntimeError("ChatGPT: access token expired (401) — refresh needed")
            if r.status_code != 200:
                raise RuntimeError(f"ChatGPT: HTTP {r.status_code}: {r.text[:300]}")

            text = _parse_conversation_response(r.text)
            tokens_in = sum(len(m.get("content", "")) // 4 for m in messages)
            tokens_out = len(text) // 4 if text else 0
            cost = 0.0
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
    body = {
        "action": "next",
        "messages": [{
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
        }],
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
                raise RuntimeError("ChatGPT: access token expired (401) — refresh needed")
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
    """Return available Codex models from live API or fallback.

    Uses same endpoint as Hermes Agent:
    chatgpt.com/backend-api/codex/models?client_version=1.0.0
    """
    if not access_token:
        return _fallback_codex_models()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{CHATGPT_HOST}/backend-api/codex/models?client_version=1.0.0",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code != 200:
                return _fallback_codex_models()
            data = r.json()
            entries = data.get("models", []) if isinstance(data, dict) else []
            if not entries:
                return _fallback_codex_models()
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
            result = [
                {"id": slug, "name": slug,
                 "supports_vision": True, "context_length": 272_000,
                 "price_in": 0.0, "price_out": 0.0, "is_free": True}
                for _, slug in sortable
            ]
            return result if result else _fallback_codex_models()
    except Exception:
        return _fallback_codex_models()


# ═══════════════════════════════════════════════════════════════════════════════
# Token lifecycle helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _oauth_extra_fields(provider) -> dict:
    extra = getattr(provider, "extra_params", None) or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    return extra.get("oauth", {}) if isinstance(extra, dict) else {}


async def ensure_fresh_token(provider, db_session=None) -> str:
    oauth = _oauth_extra_fields(provider)
    access_token = provider.api_key
    expires_at = oauth.get("expires_at", 0)
    refresh_token = oauth.get("refresh_token", "")

    if access_token and expires_at > time.time():
        return access_token

    if refresh_token:
        log.info("ChatGPT OAuth: token expired, refreshing...")
        try:
            new_tokens = await refresh_oauth_token(refresh_token)
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
            log.warning("ChatGPT OAuth: refresh failed: %s", e)
            if access_token:
                return access_token
            raise

    if access_token:
        return access_token
    raise RuntimeError("ChatGPT OAuth: no tokens — re-authentication required")


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

async def _async_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)


def _convert_messages(messages: list[dict]) -> list[dict]:
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
            "content": {"content_type": "text", "parts": [str(content)]},
        })
    return result


def _parse_conversation_response(text: str) -> str:
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
                parts = (chunk.get("message", {}).get("content", {}).get("parts", []))
                if parts:
                    last_text = "".join(p if isinstance(p, str) else str(p) for p in parts)
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


def _fallback_codex_models() -> list[dict]:
    """Fallback Codex model list (same as Hermes Agent DEFAULT_CODEX_MODELS)."""
    return [
        {"id": mid, "name": mid,
         "supports_vision": True, "context_length": 272_000,
         "price_in": 0.0, "price_out": 0.0, "is_free": True}
        for mid in DEFAULT_CODEX_MODELS
    ]


def _fallback_models() -> list[dict]:
    return [
        {
            "id": m["id"], "name": m["name"],
            "supports_vision": m["vision"], "context_length": m["ctx"],
            "price_in": 0.0, "price_out": 0.0, "is_free": True,
        }
        for m in CHATGPT_WEB_MODELS
    ]
