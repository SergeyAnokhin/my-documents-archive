"""
ChatGPT OAuth authentication router.

Uses OpenAI's proprietary device-auth flow (same as ChatGPT desktop app):
  1. POST /device-code → start device flow (returns device_auth_id + user_code)
  2. POST /token         → poll for authorization + exchange for OAuth tokens
  3. GET  /status        → check auth status
  4. POST /refresh       → manually refresh tokens
  5. DELETE /logout/{id} → remove tokens
"""
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AIProvider
from ..services import chatgpt_web

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/chatgpt", tags=["chatgpt-oauth"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class DeviceCodeStartResponse(BaseModel):
    device_auth_id: str
    user_code: str
    verification_uri: str
    interval: int = 5


class TokenPollRequest(BaseModel):
    device_auth_id: str
    user_code: str
    interval: int = 5
    provider_id: int = 0


class TokenPollResponse(BaseModel):
    status: str
    access_token: str = ""
    refresh_token: str = ""
    expires_in: int = 0
    message: str = ""


class AuthStatusResponse(BaseModel):
    connected: bool
    provider_id: int = 0
    expires_at: float = 0.0
    has_refresh_token: bool = False
    model: str = ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/device-code", response_model=DeviceCodeStartResponse)
async def start_device_code():
    """Step 1: Request device auth user code from OpenAI."""
    try:
        result = await chatgpt_web.start_device_flow()
        return DeviceCodeStartResponse(
            device_auth_id=result.device_auth_id,
            user_code=result.user_code,
            verification_uri=result.verification_uri,
            interval=result.interval,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Device code start failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/token", response_model=TokenPollResponse)
async def poll_token(body: TokenPollRequest, db: Session = Depends(get_db)):
    """Step 2-4: Poll for authorization, exchange code for tokens."""
    try:
        token = await chatgpt_web.poll_for_token(
            device_auth_id=body.device_auth_id,
            user_code=body.user_code,
            interval=body.interval,
        )
    except RuntimeError as e:
        msg = str(e)
        if msg == "authorization_pending":
            return TokenPollResponse(status="pending")
        if "expired" in msg.lower():
            return TokenPollResponse(status="expired", message=msg)
        if "declined" in msg.lower() or "denied" in msg.lower():
            return TokenPollResponse(status="denied", message=msg)
        log.error("Token poll error: %s", msg)
        return TokenPollResponse(status="error", message=msg)
    except Exception as e:
        log.exception("Token poll failed")
        return TokenPollResponse(status="error", message=str(e))

    # Save tokens to provider
    if body.provider_id:
        provider = db.query(AIProvider).filter(
            AIProvider.id == body.provider_id,
        ).first()
        if provider:
            provider.api_key = token.access_token
            extra = getattr(provider, "extra_params", None) or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            extra["oauth"] = {
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at,
                "token_type": token.token_type,
            }
            provider.extra_params = extra
            db.commit()
            log.info("ChatGPT OAuth: tokens saved for provider %s", provider.name)

    return TokenPollResponse(
        status="authorized",
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_in=token.expires_in,
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(provider_id: int, db: Session = Depends(get_db)):
    provider = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not provider:
        return AuthStatusResponse(connected=False)

    oauth = {}
    extra = getattr(provider, "extra_params", None) or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if isinstance(extra, dict):
        oauth = extra.get("oauth", {})

    expires_at = oauth.get("expires_at", 0)
    access_token = provider.api_key or ""
    refresh_token = oauth.get("refresh_token", "")

    return AuthStatusResponse(
        connected=bool(access_token and (expires_at > time.time() or refresh_token)),
        provider_id=provider.id,
        expires_at=expires_at,
        has_refresh_token=bool(refresh_token),
        model=provider.model or "",
    )


@router.post("/refresh", response_model=AuthStatusResponse)
async def refresh_token(provider_id: int, db: Session = Depends(get_db)):
    provider = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        access_token = await chatgpt_web.ensure_fresh_token(provider, db)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))

    oauth = {}
    extra = getattr(provider, "extra_params", None) or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if isinstance(extra, dict):
        oauth = extra.get("oauth", {})

    return AuthStatusResponse(
        connected=bool(access_token),
        provider_id=provider.id,
        expires_at=oauth.get("expires_at", 0),
        has_refresh_token=bool(oauth.get("refresh_token", "")),
        model=provider.model or "",
    )


@router.delete("/logout/{provider_id}")
async def logout(provider_id: int, db: Session = Depends(get_db)):
    provider = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    provider.api_key = ""
    extra = getattr(provider, "extra_params", None) or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if isinstance(extra, dict):
        extra.pop("oauth", None)
    provider.extra_params = extra
    db.commit()

    return {"status": "logged_out", "provider_id": provider_id}
