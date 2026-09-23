"""Supabase Auth: verify access tokens (ES256 via JWKS) and map them to our
MongoDB user records. Passwords/sessions live entirely in Supabase."""
import asyncio
import logging
import os
from typing import Optional

import httpx
import jwt
from jwt import PyJWKClient
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
ISSUER = f"{SUPABASE_URL}/auth/v1"
_jwks: Optional[PyJWKClient] = PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True) if SUPABASE_URL else None


def enabled() -> bool:
    return bool(SUPABASE_URL)


class IdentityConflict(Exception):
    """The inbox behind this login is already linked to a different Supabase
    identity (e.g. a Gmail +tag / dotted alias of an existing account)."""


def verify_access_token(token: str) -> Optional[dict]:
    """Return verified claims (sub, email) or None. Signature, issuer,
    audience and expiry are all checked; only ES256 (JWKS) or legacy HS256
    with SUPABASE_JWT_SECRET are accepted."""
    if not _jwks:
        return None
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "ES256":
            key = _jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["ES256"], issuer=ISSUER, audience="authenticated")
        elif alg == "HS256" and os.environ.get("SUPABASE_JWT_SECRET"):
            claims = jwt.decode(token, os.environ["SUPABASE_JWT_SECRET"], algorithms=["HS256"],
                                issuer=ISSUER, audience="authenticated")
        else:
            return None
        if not claims.get("sub") or not claims.get("email"):
            return None
        return claims
    except Exception as e:
        logger.debug("supabase token rejected: %s", e)
        return None


async def resolve_user_email(db: AsyncIOMotorDatabase, claims: dict) -> Optional[str]:
    """Map a verified Supabase identity to our account email. First login
    links by (alias-collapsed) email and stamps `supabase_sub`; brand-new
    users get a trial shell row. Never trusts anything from the client."""
    from auth import canonical_email, resolve_account_email, _now
    sub = claims["sub"]
    user = await db.users.find_one({"supabase_sub": sub}, {"email": 1, "last_login_at": 1})
    if not user:
        email = await resolve_account_email(db, claims["email"])
        user = await db.users.find_one({"email": email}, {"email": 1, "supabase_sub": 1, "last_login_at": 1})
        if user and user.get("supabase_sub") not in (None, sub):
            logger.warning("login %s resolves to account %s which is linked to another supabase identity",
                           claims["email"], email)
            raise IdentityConflict(email)
        if not user:
            await db.users.insert_one({
                "email": email, "email_key": canonical_email(email), "supabase_sub": sub,
                "trial_word_used": 0, "trial_scene_used": 0,
                "created_at": _now().isoformat(), "last_login_at": None,
            })
            user = {"email": email, "last_login_at": None}
        else:
            await db.users.update_one({"email": email}, {"$set": {"supabase_sub": sub}})
    if user.get("last_login_at") is None:
        await db.users.update_one({"email": user["email"]}, {"$set": {"last_login_at": _now().isoformat()}})
        from notify import notify_owner
        import kit
        notify_owner("New free trial", "Someone just started a free trial",
                     [f"<b>{user['email']}</b> created an account.", "They get 5 free words and 1 free scene."])
        kit.tag_subscriber(user["email"], kit.TAG_TRIAL)
    return user["email"]


# --- Admin helpers (service-role key; server only) --------------------------
def _admin_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def admin_create_user(email: str) -> Optional[str]:
    """Pre-create a confirmed Supabase user (no password) so 'Forgot password'
    works for existing members. Returns the Supabase user id, or None if the
    user already exists / key missing."""
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return None
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{ISSUER}/admin/users", headers=_admin_headers(),
                         json={"email": email, "email_confirm": True})
    if r.status_code in (200, 201):
        return r.json().get("id")
    logger.info("supabase admin create %s → %s %s", email, r.status_code, r.text[:120])
    return None


async def send_password_reset(email: str, redirect_to: str) -> bool:
    """Ask Supabase to email a reset/set-password link (uses its SMTP)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{ISSUER}/recover", json={"email": email},
                         params={"redirect_to": redirect_to},
                         headers={"apikey": os.environ.get("SUPABASE_ANON_KEY", ""),
                                  "Content-Type": "application/json"})
    return r.status_code in (200, 204)


async def link_existing_users(db: AsyncIOMotorDatabase) -> None:
    """Startup, idempotent: create Supabase identities for legacy accounts so
    their first 'Forgot password' email works. Skips users already linked."""
    if not (enabled() and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return
    async for u in db.users.find({"supabase_sub": {"$exists": False}}, {"email": 1}):
        sub = await admin_create_user(u["email"])
        if sub:
            await db.users.update_one({"_id": u["_id"]}, {"$set": {"supabase_sub": sub}})
        await asyncio.sleep(0.2)
