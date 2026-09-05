"""Magic-link auth + subscription gate for the Accent Coach app.

Design goals:
- Zero passwords. Users log in with a one-tap link emailed via Resend.
- Access model: every user has a trial budget (1 word + 1 scene) and an
  optional active membership. Membership state is populated by Kajabi
  webhooks (see kajabi.py).
- Cookie-based JWT session so /api/auth/me can be read from the SPA.

Environment (backend/.env):
    RESEND_API_KEY       - transactional email
    SENDER_EMAIL         - e.g. onboarding@resend.dev (Resend shared) or login@yourdomain
    SENDER_NAME          - display name in the From: header
    JWT_SECRET           - session token signing secret
    APP_PUBLIC_URL       - used to build the magic-link URL sent in email

Collections:
    users         { email (unique), trial_word_used, trial_scene_used,
                    created_at, last_login_at }
    magic_links   { token (unique), email, created_at, expires_at, consumed }
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import resend
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr

logger = logging.getLogger(__name__)

# --- Config -----------------------------------------------------------------
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
JWT_COOKIE_NAME = "accent_session"
JWT_DAYS = 30                       # session lifetime
MAGIC_LINK_TTL_MIN = 15             # magic link expiry
MAGIC_LINK_RATE_LIMIT_MIN = 1       # 1 magic link per minute per email
TRIAL_WORD_LIMIT = 1
TRIAL_SCENE_LIMIT = 1

APP_PUBLIC_URL = os.environ["APP_PUBLIC_URL"].rstrip("/")
SENDER_EMAIL = os.environ["SENDER_EMAIL"]
SENDER_NAME = os.environ.get("SENDER_NAME", "Accent Coach")
FROM_HEADER = f"{SENDER_NAME} <{SENDER_EMAIL}>"

resend.api_key = os.environ["RESEND_API_KEY"]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --- Models -----------------------------------------------------------------
class RequestMagicLinkBody(BaseModel):
    email: EmailStr


class AuthMeResponse(BaseModel):
    authenticated: bool
    email: Optional[str] = None
    subscription_status: str = "none"        # "active" | "trialing" | "none"
    subscription_offer_title: Optional[str] = None
    subscription_end_at: Optional[str] = None
    trial_word_used: int = 0
    trial_scene_used: int = 0
    trial_word_limit: int = TRIAL_WORD_LIMIT
    trial_scene_limit: int = TRIAL_SCENE_LIMIT
    monthly_offer_url: str = ""
    annual_offer_url: str = ""
    member_portal_url: str = ""


# --- Helpers ----------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _issue_jwt(email: str) -> str:
    payload = {
        "sub": email,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(days=JWT_DAYS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _decode_jwt(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def _magic_link_email_html(login_url: str) -> str:
    return f"""
<!doctype html>
<html>
<body style="margin:0;padding:0;background:#F5F1EA;font-family:Georgia,serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F5F1EA;padding:48px 20px;">
    <tr>
      <td align="center">
        <table width="480" cellpadding="0" cellspacing="0" border="0" style="background:#FFFFFF;border:1px solid #E5DED0;">
          <tr>
            <td style="padding:32px 32px 0 32px;">
              <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:0.28em;text-transform:uppercase;color:#8B8578;">
                Accent Coach · Sign in
              </div>
              <h1 style="margin:12px 0 20px 0;font-family:'Cormorant Garamond',Georgia,serif;font-weight:400;font-size:32px;color:#2A2620;">
                Your sign-in link
              </h1>
              <p style="margin:0 0 24px 0;font-family:'Crimson Text',Georgia,serif;font-size:16px;line-height:1.6;color:#2A2620;">
                Tap the button below to sign in. This link is good for 15 minutes and can only be used once.
              </p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:8px 32px 24px 32px;">
              <a href="{login_url}"
                 style="display:inline-block;padding:14px 28px;background:#2A2620;color:#F5F1EA;text-decoration:none;font-family:'IBM Plex Mono',monospace;font-size:12px;letter-spacing:0.24em;text-transform:uppercase;">
                Sign in to Accent Coach
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 32px 32px;">
              <p style="margin:0;font-family:'Crimson Text',Georgia,serif;font-size:14px;line-height:1.6;color:#8B8578;">
                If the button doesn't work, paste this URL into your browser:<br/>
                <span style="word-break:break-all;color:#5A5548;">{login_url}</span>
              </p>
              <p style="margin:20px 0 0 0;font-family:'Crimson Text',Georgia,serif;font-size:13px;line-height:1.6;color:#8B8578;font-style:italic;">
                Didn't request this? You can safely ignore this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
""".strip()


async def _send_magic_link_email(email: str, login_url: str) -> None:
    params = {
        "from": FROM_HEADER,
        "to": [email],
        "subject": "Your Accent Coach sign-in link",
        "html": _magic_link_email_html(login_url),
    }
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Sent magic link to {email}: {result.get('id')}")
    except Exception as e:
        logger.exception(f"Resend send failed for {email}: {e}")
        raise HTTPException(status_code=502, detail="email_send_failed")


# --- Membership status helper ----------------------------------------------
async def _membership_status(db: AsyncIOMotorDatabase, email: str) -> dict:
    """Return {status, offer_title, subscription_end_at} for the given email.

    Status precedence:
        active   - there's at least one membership row with status=active AND
                   (subscription_end_at is null OR in the future)
        none     - otherwise
    """
    now = _now()
    docs = await db.memberships.find({"user_email": email}).to_list(50)
    best = None
    for m in docs:
        if m.get("status") != "active":
            continue
        end = m.get("subscription_end_at")
        if end:
            try:
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if end_dt <= now:
                    continue
            except Exception:
                pass
        best = m
        break
    if best:
        return {
            "status": "active",
            "offer_title": best.get("offer_title"),
            "subscription_end_at": best.get("subscription_end_at"),
        }
    return {"status": "none", "offer_title": None, "subscription_end_at": None}


# --- Router factory --------------------------------------------------------
def create_auth_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    async def _get_or_create_user(email: str) -> dict:
        user = await db.users.find_one({"email": email})
        if user:
            return user
        doc = {
            "email": email,
            "trial_word_used": 0,
            "trial_scene_used": 0,
            "created_at": _now().isoformat(),
            "last_login_at": None,
        }
        await db.users.insert_one(doc)
        return doc

    @router.post("/request-magic-link")
    async def request_magic_link(body: RequestMagicLinkBody):
        email = _normalize_email(body.email)
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail="invalid_email")

        # Rate limit: 1 request/min/email.
        cutoff = _now() - timedelta(minutes=MAGIC_LINK_RATE_LIMIT_MIN)
        recent = await db.magic_links.find_one({
            "email": email,
            "created_at": {"$gt": cutoff.isoformat()},
        })
        if recent:
            # Silent success — don't leak that a link was recently sent.
            return {"ok": True}

        await _get_or_create_user(email)

        token = secrets.token_urlsafe(32)
        expires_at = _now() + timedelta(minutes=MAGIC_LINK_TTL_MIN)
        await db.magic_links.insert_one({
            "token": token,
            "email": email,
            "created_at": _now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "expires_at_dt": expires_at,   # BSON datetime for the TTL index
            "consumed": False,
        })

        login_url = f"{APP_PUBLIC_URL}/auth/verify?token={token}"
        await _send_magic_link_email(email, login_url)
        return {"ok": True}

    @router.get("/verify")
    async def verify_magic_link(token: str, response: Response):
        """Consume a magic-link token; if valid, set the session cookie.

        Returns JSON so the frontend /auth/verify page can redirect.
        """
        link = await db.magic_links.find_one({"token": token})
        if not link or link.get("consumed"):
            raise HTTPException(status_code=400, detail="invalid_or_used_link")
        try:
            expires_at = datetime.fromisoformat(link["expires_at"])
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_link")
        if expires_at < _now():
            raise HTTPException(status_code=400, detail="expired_link")

        email = link["email"]
        await db.magic_links.update_one(
            {"token": token},
            {"$set": {"consumed": True, "consumed_at": _now().isoformat()}},
        )
        await db.users.update_one(
            {"email": email},
            {"$set": {"last_login_at": _now().isoformat()}},
        )

        session = _issue_jwt(email)
        # SameSite=lax so we still get the cookie when the user clicks the
        # link from their email client (which is a cross-site GET).
        response.set_cookie(
            key=JWT_COOKIE_NAME,
            value=session,
            max_age=JWT_DAYS * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=True,
            path="/",
        )
        return {"ok": True, "email": email}

    @router.post("/logout")
    async def logout(response: Response):
        response.delete_cookie(JWT_COOKIE_NAME, path="/")
        return {"ok": True}

    @router.get("/me", response_model=AuthMeResponse)
    async def me(request: Request):
        token = request.cookies.get(JWT_COOKIE_NAME)
        email = _decode_jwt(token) if token else None
        offer_urls = {
            "monthly_offer_url": os.environ.get("KAJABI_MONTHLY_OFFER_URL", ""),
            "annual_offer_url": os.environ.get("KAJABI_ANNUAL_OFFER_URL", ""),
            "member_portal_url": os.environ.get("KAJABI_MEMBER_PORTAL_URL", ""),
        }
        if not email:
            return AuthMeResponse(authenticated=False, **offer_urls)

        user = await db.users.find_one({"email": email})
        if not user:
            # Cookie references a deleted user — treat as logged out.
            return AuthMeResponse(authenticated=False, **offer_urls)

        status = await _membership_status(db, email)
        return AuthMeResponse(
            authenticated=True,
            email=email,
            subscription_status=status["status"],
            subscription_offer_title=status["offer_title"],
            subscription_end_at=status["subscription_end_at"],
            trial_word_used=user.get("trial_word_used", 0),
            trial_scene_used=user.get("trial_scene_used", 0),
            **offer_urls,
        )

    return router


# --- Access gate (used by other routes) ------------------------------------
class Actor(BaseModel):
    """Result of gating a request. `allowed` is True if the caller can proceed.
    If `allowed`, `consumed_trial_kind` may be set to "word" or "scene" telling
    server.py to increment that counter after a successful response."""
    email: str
    is_subscriber: bool
    allowed: bool
    consumed_trial_kind: Optional[str] = None
    reason: Optional[str] = None


async def require_access(
    request: Request,
    db: AsyncIOMotorDatabase,
    kind: str,           # "word" or "scene"
) -> Actor:
    """Gate a route on: (a) logged in, (b) active member OR trial remaining.

    Raises HTTPException(401) if not logged in, HTTPException(402) if trial
    exhausted and no membership. On success, returns an Actor. The caller
    must call `consume_trial(db, actor)` AFTER the operation succeeds.
    """
    token = request.cookies.get(JWT_COOKIE_NAME)
    email = _decode_jwt(token) if token else None
    if not email:
        raise HTTPException(status_code=401, detail="not_authenticated")

    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=401, detail="unknown_user")

    status = await _membership_status(db, email)
    is_sub = status["status"] == "active"
    if is_sub:
        return Actor(email=email, is_subscriber=True, allowed=True)

    if kind == "word":
        used = user.get("trial_word_used", 0)
        limit = TRIAL_WORD_LIMIT
    elif kind == "scene":
        used = user.get("trial_scene_used", 0)
        limit = TRIAL_SCENE_LIMIT
    else:
        raise HTTPException(status_code=500, detail="invalid_gate_kind")

    if used >= limit:
        raise HTTPException(
            status_code=402,
            detail={"code": "trial_exhausted", "kind": kind},
        )
    return Actor(email=email, is_subscriber=False, allowed=True,
                 consumed_trial_kind=kind)


async def consume_trial(db: AsyncIOMotorDatabase, actor: Actor) -> None:
    """Increment the trial counter, only if this call actually used a trial."""
    if actor.is_subscriber or not actor.consumed_trial_kind:
        return
    field = f"trial_{actor.consumed_trial_kind}_used"
    await db.users.update_one({"email": actor.email}, {"$inc": {field: 1}})


async def require_login(request: Request, db: AsyncIOMotorDatabase) -> str:
    """Just verify the caller is logged in. Returns their email."""
    token = request.cookies.get(JWT_COOKIE_NAME)
    email = _decode_jwt(token) if token else None
    if not email:
        raise HTTPException(status_code=401, detail="not_authenticated")
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=401, detail="unknown_user")
    return email


async def require_subscriber(request: Request, db: AsyncIOMotorDatabase) -> str:
    """Verify caller is logged in AND has an active membership."""
    email = await require_login(request, db)
    status = await _membership_status(db, email)
    if status["status"] != "active":
        raise HTTPException(
            status_code=402,
            detail={"code": "subscription_required"},
        )
    return email


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create the indexes auth relies on. Safe to call multiple times."""
    await db.users.create_index("email", unique=True)
    await db.magic_links.create_index("token", unique=True)
    await db.magic_links.create_index("email")
    # TTL on magic links (60 min so we have grace for testing/debugging).
    try:
        await db.magic_links.create_index(
            "expires_at_dt", expireAfterSeconds=3600
        )
    except Exception:
        pass
    await db.memberships.create_index(
        [("user_email", 1), ("offer_id", 1)], unique=True
    )
    await db.webhook_events.create_index(
        [("provider", 1), ("external_event_id", 1)], unique=True
    )
