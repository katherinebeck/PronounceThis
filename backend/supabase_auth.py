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
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
ISSUER = f"{SUPABASE_URL}/auth/v1"
_jwks: Optional[PyJWKClient] = (
    PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True, timeout=6) if SUPABASE_URL else None
)
# Our own JWKS cache: async fetch, long-lived, pre-warmed, keeps the last good keys on failure.
_keyset = {"keys": {}, "fetched_at": 0.0, "lock": asyncio.Lock()}
KEYS_TTL_S = 12 * 3600
ROTATION_RETRY_S = 60


async def _refresh_keys(force: bool = False) -> None:
    import time
    now = time.time()
    if not force and _keyset["keys"] and now - _keyset["fetched_at"] < KEYS_TTL_S:
        return
    async with _keyset["lock"]:
        if not force and _keyset["keys"] and time.time() - _keyset["fetched_at"] < KEYS_TTL_S:
            return
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{ISSUER}/.well-known/jwks.json")
                r.raise_for_status()
            keys = {k["kid"]: jwt.PyJWK(k).key for k in r.json().get("keys", []) if k.get("kid")}
            if keys:
                _keyset.update(keys=keys, fetched_at=time.time())
                logger.info("supabase jwks refreshed (%d keys)", len(keys))
        except Exception as exc:  # noqa: BLE001
            logger.warning("supabase jwks fetch failed (keeping %d cached keys): %s", len(_keyset["keys"]), exc)


def keys_loaded() -> bool:
    return bool(_keyset["keys"]) or bool(os.environ.get("SUPABASE_JWT_SECRET"))


def prewarm() -> None:
    if SUPABASE_URL:
        asyncio.get_running_loop().create_task(_refresh_keys(force=True))


async def verify_access_token_async(token: str) -> Optional[dict]:
    """Verify with our cached key set; never blocks the loop on a network call."""
    if not SUPABASE_URL:
        return None
    try:
        header = jwt.get_unverified_header(token)
        alg, kid = header.get("alg"), header.get("kid")
        if alg == "HS256" and os.environ.get("SUPABASE_JWT_SECRET"):
            claims = jwt.decode(token, os.environ["SUPABASE_JWT_SECRET"], algorithms=["HS256"],
                                issuer=ISSUER, audience="authenticated")
        elif alg == "ES256":
            await _refresh_keys()
            key = _keyset["keys"].get(kid)
            if key is None:
                import time
                if time.time() - _keyset["fetched_at"] > ROTATION_RETRY_S:
                    await _refresh_keys(force=True)  # key rotation
                    key = _keyset["keys"].get(kid)
            if key is None:
                return None
            claims = jwt.decode(token, key, algorithms=["ES256"], issuer=ISSUER, audience="authenticated")
        else:
            return None
        if not claims.get("sub") or not claims.get("email"):
            return None
        return claims
    except Exception as e:  # noqa: BLE001
        logger.debug("supabase token rejected: %s", e)
        return None


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
            if (claims["email"] or "").lower() == (user["email"] or "").lower():
                # Same verified address, new Supabase identity (e.g. switched password → Google): re-link.
                logger.info("login %s re-linked from stale supabase identity to a new one", email)
            else:
                logger.warning("login %s resolves to account %s which is linked to another supabase identity",
                               claims["email"], email)
                raise IdentityConflict(email)
        if not user:
            try:
                await db.users.insert_one({
                    "email": email, "email_key": canonical_email(email), "supabase_sub": sub,
                    "trial_word_used": 0, "trial_scene_used": 0, "guided_trial": True,
                    "created_at": _now().isoformat(), "last_login_at": None,
                })
                user = {"email": email, "last_login_at": None}
            except DuplicateKeyError:
                # Concurrent first-login requests raced; the other one created the row.
                await db.users.update_one({"email": email}, {"$set": {"supabase_sub": sub}})
                user = await db.users.find_one({"email": email}, {"email": 1, "last_login_at": 1}) or {"email": email, "last_login_at": None}
        else:
            await db.users.update_one({"email": email}, {"$set": {"supabase_sub": sub}})
    if user.get("last_login_at") is None:
        await db.users.update_one({"email": user["email"]}, {"$set": {"last_login_at": _now().isoformat()}})
        from auth import _membership_status
        if (await _membership_status(db, user["email"]))["status"] != "active":
            from notify import notify_owner
            import kit
            notify_owner("New free trial", "Someone just started a free trial",
                         [f"<b>{user['email']}</b> created an account.", "They get 1 free word and the sample audition scene."])
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


async def ensure_identity(email: str) -> bool:
    """Make sure a Supabase identity exists for `email` (create-if-missing).
    Returns True when it exists afterwards, False if the key is missing or
    Supabase refused."""
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return False
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{ISSUER}/admin/users", headers=_admin_headers(),
                         json={"email": email, "email_confirm": True})
    if r.status_code in (200, 201):
        return True
    body = r.text.lower()
    return r.status_code == 422 and ("exists" in body or "already" in body)


async def admin_user_id(email: str) -> Optional[str]:
    """Supabase user id for an exact (case-insensitive) email, or None."""
    email = email.strip().lower()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{ISSUER}/admin/users", headers=_admin_headers(),
                        params={"filter": email, "page": 1, "per_page": 100})
    if r.status_code != 200:
        logger.warning("supabase admin list %s → %s", email, r.status_code)
        return None
    exact = [u for u in r.json().get("users", []) if (u.get("email") or "").lower() == email]
    return exact[0]["id"] if len(exact) == 1 else None


async def admin_set_password(email: str, password: str) -> bool:
    """Server-side password set (post-checkout onboarding). Creates the
    identity if needed, marks the email confirmed. True on success."""
    if not await ensure_identity(email):
        return False
    uid = await admin_user_id(email)
    if not uid:
        return False
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.put(f"{ISSUER}/admin/users/{uid}", headers=_admin_headers(),
                        json={"password": password, "email_confirm": True})
    if r.status_code != 200:
        logger.warning("supabase admin set password %s → %s", email, r.status_code)
    return r.status_code == 200


async def generate_set_password_link(email: str, redirect_to: str) -> Optional[str]:
    """Server-generated recovery link (Admin API `generate_link`) — lets us
    email it ourselves or hand it to the admin to copy. None on failure."""
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return None
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{ISSUER}/admin/generate_link", headers=_admin_headers(),
                         json={"type": "recovery", "email": email, "redirect_to": redirect_to})
    if r.status_code in (200, 201):
        return r.json().get("action_link")
    logger.warning("supabase generate_link %s → %s %s", email, r.status_code, r.text[:160])
    return None


async def link_existing_users(db: AsyncIOMotorDatabase) -> None:
    """Startup, idempotent: create Supabase identities for legacy accounts so
    their first 'Forgot password' email works. Skips users already linked."""
    if not (enabled() and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return
    async for u in db.users.find({"supabase_sub": {"$exists": False}, "supabase_link_checked": {"$ne": True}}, {"email": 1}):
        sub = await admin_create_user(u["email"])
        update = {"supabase_sub": sub} if sub else {"supabase_link_checked": True}
        await db.users.update_one({"_id": u["_id"]}, {"$set": update})
        await asyncio.sleep(0.2)
