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
JWT_DAYS = 90                       # session lifetime
MAGIC_LINK_TTL_MIN = 15             # magic link expiry
MAGIC_LINK_RATE_LIMIT_MIN = 1       # 1 magic link per minute per email
TRIAL_WORD_LIMIT = 5
TRIAL_SCENE_LIMIT = 1

APP_PUBLIC_URL = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
SENDER_EMAIL = os.environ["SENDER_EMAIL"]
SENDER_NAME = "Pronounce This"
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
    # Kept for now to preserve backwards-compat during the Kajabi → Stripe
    # transition; the paywall now uses `stripe_prices` instead.
    monthly_offer_url: str = ""
    annual_offer_url: str = ""
    member_portal_url: str = ""
    # Stripe subscription plan surface for the paywall.
    stripe_prices: list = []
    has_stripe_customer: bool = False
    is_admin: bool = False


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
                Pronounce This · Sign in
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
                Sign in to Pronounce This
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
        "subject": "Your Pronounce This sign-in link",
        "html": _magic_link_email_html(login_url),
    }
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Sent magic link to {email}: {result.get('id')}")
    except Exception as e:
        logger.exception(f"Resend send failed for {email}: {e}")
        # Resend testing mode error: "You can only send testing emails to
        # your own email address" until a domain is verified in Resend.
        err_msg = str(e).lower()
        if (
            "testing emails to your own" in err_msg
            or "verify a domain" in err_msg
            or "restricted" in err_msg
        ):
            raise HTTPException(
                status_code=400,
                detail="email_delivery_pending_domain_verification",
            )
        # Any other Resend/network failure — still a client-visible error, but
        # return 400 (not 5xx) so Cloudflare passes the response through.
        raise HTTPException(status_code=400, detail="email_send_failed")


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
    async def request_magic_link(body: RequestMagicLinkBody, request: Request):
        email = _normalize_email(body.email)
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail="invalid_email")

        # Abuse caps: 5 links/email/hour, 20 links/IP/hour (429), then the
        # gentler 1/min/email silent limiter below.
        rate_limit(f"ml:email:{email}", 5, 3600)
        rate_limit(f"ml:ip:{client_ip(request)}", 20, 3600)

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

        # Build the login URL from the request's origin so magic links work
        # on whatever domain the app is deployed to (preview or production).
        # Fall back to APP_PUBLIC_URL env only if the request has no Origin
        # header (e.g. server-to-server invocation).
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            # Origin is like "https://foo.com"; Referer may include a path.
            from urllib.parse import urlparse
            u = urlparse(origin)
            base = f"{u.scheme}://{u.netloc}"
        else:
            base = APP_PUBLIC_URL
        login_url = f"{base}/auth/verify?token={token}"
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
        # Static plan shape (backend does not need Stripe here — checkout is
        # created on demand). Prices come from Stripe by lookup_key.
        stripe_prices = [
            {"lookup_key": "accent_coach_monthly", "label": "Monthly",
             "amount": 9, "currency": "usd", "interval": "month"},
            {"lookup_key": "accent_coach_yearly", "label": "Annual",
             "amount": 90, "currency": "usd", "interval": "year",
             "savings_note": "Save $18 vs monthly"},
        ]
        if not email:
            return AuthMeResponse(
                authenticated=False,
                stripe_prices=stripe_prices,
                has_stripe_customer=False,
                **offer_urls,
            )

        user = await db.users.find_one({"email": email})
        if not user:
            return AuthMeResponse(
                authenticated=False,
                stripe_prices=stripe_prices,
                has_stripe_customer=False,
                **offer_urls,
            )

        status = await _membership_status(db, email)

        # Self-heal: if the app doesn't show this user as an active member,
        # they may have paid on Stripe but the local state didn't catch up
        # (missed webhook, race with /status polling, etc). Try to pull
        # their state directly from Stripe. Fires for anyone with either a
        # stored stripe_customer_id OR none (in which case we look up the
        # customer by email — covers the "customer link never saved" edge
        # case). Rate-limited to once per 5 min per user so /me stays fast.
        if status["status"] != "active":
            last_sync = user.get("last_stripe_sync_at")
            should_sync = True
            if last_sync:
                try:
                    last_dt = datetime.fromisoformat(
                        last_sync.replace("Z", "+00:00")
                    )
                    if (_now() - last_dt) < timedelta(minutes=5):
                        should_sync = False
                except Exception:
                    pass
            if should_sync:
                try:
                    from stripe_payments import sync_from_stripe_customer
                    result = await sync_from_stripe_customer(db, email)
                    await db.users.update_one(
                        {"email": email},
                        {"$set": {"last_stripe_sync_at": _now().isoformat()}},
                    )
                    if result.get("active_found"):
                        status = await _membership_status(db, email)
                except Exception as exc:
                    logger.warning(
                        f"self-heal stripe sync failed for {email}: {exc}"
                    )

        # Re-read user so we surface the has_stripe_customer flag correctly
        # after a possible self-heal that just linked the customer.
        user = await db.users.find_one({"email": email}) or user

        return AuthMeResponse(
            authenticated=True,
            email=email,
            subscription_status=status["status"],
            subscription_offer_title=status["offer_title"],
            subscription_end_at=status["subscription_end_at"],
            trial_word_used=user.get("trial_word_used", 0),
            trial_scene_used=user.get("trial_scene_used", 0),
            stripe_prices=stripe_prices,
            has_stripe_customer=bool(user.get("stripe_customer_id")),
            is_admin=is_admin_email(email),
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


# --- Simple in-process sliding-window rate limiter --------------------------
_RL_BUCKETS: dict = {}


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(key: str, limit: int, window_seconds: int) -> None:
    """Raise 429 if `key` exceeded `limit` events in the trailing window."""
    import time as _time
    now = _time.time()
    bucket = [t for t in _RL_BUCKETS.get(key, []) if now - t < window_seconds]
    if len(bucket) >= limit:
        _RL_BUCKETS[key] = bucket
        raise HTTPException(status_code=429, detail="rate_limited")
    bucket.append(now)
    _RL_BUCKETS[key] = bucket
    if len(_RL_BUCKETS) > 50_000:   # crude memory guard
        _RL_BUCKETS.clear()


def is_admin_email(email: Optional[str]) -> bool:
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    return bool(email) and email.lower() in admins


async def optional_login(request: Request, db: AsyncIOMotorDatabase) -> Optional[str]:
    """Email of the logged-in caller, or None (never raises)."""
    token = request.cookies.get(JWT_COOKIE_NAME)
    email = _decode_jwt(token) if token else None
    if not email:
        return None
    user = await db.users.find_one({"email": email}, {"_id": 0, "email": 1})
    return email if user else None


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


async def require_admin(request: Request, db: AsyncIOMotorDatabase) -> str:
    """Verify caller is a logged-in admin. Admins are listed in ADMIN_EMAILS
    env var (comma-separated). Returns the admin's email on success."""
    email = await require_login(request, db)
    admins = {
        e.strip().lower()
        for e in os.environ.get("ADMIN_EMAILS", "").split(",")
        if e.strip()
    }
    if not admins:
        # No admins configured yet — deny everything explicitly so nothing
        # ships "open by default" if the env var is missing.
        raise HTTPException(status_code=403, detail="admin_not_configured")
    if email.lower() not in admins:
        raise HTTPException(status_code=403, detail="not_admin")
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
