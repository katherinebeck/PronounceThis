"""Kajabi webhook receiver + membership state management.

Handles the two documented outbound Kajabi events we need:

    purchase           - fired on the initial purchase / subscription creation.
                         Grants membership.
    payment_succeeded  - fired on each subsequent successful recurring charge.
                         Refreshes the last_payment_at timestamp; keeps status=active.

Kajabi does NOT document a signature header, refund event, or cancellation
event on its public outbound webhook system. We therefore:

  1. Protect the endpoint with a high-entropy URL token (KAJABI_WEBHOOK_TOKEN)
     compared in constant time.
  2. Accept cancellations via a separate /api/kajabi/cancel endpoint that
     the customer wires up as a Kajabi Automation "HTTP action" triggered by
     the "Recurring payments cancellation" trigger. The Automation POSTs
     { email, subscription_end_at } to our endpoint.
  3. (Future work — Phase 4) Nightly reconciliation via Kajabi Public API
     to catch missed cancellations/refunds.

Envelope reference:
    https://help.kajabi.com/api-reference/webhooks/purchase-sample
    https://help.kajabi.com/api-reference/webhooks/payment-succeeded-sample
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

KAJABI_WEBHOOK_TOKEN = os.environ["KAJABI_WEBHOOK_TOKEN"]
KAJABI_API_CLIENT_ID = os.environ.get("KAJABI_API_CLIENT_ID", "").strip()
KAJABI_API_CLIENT_SECRET = os.environ.get("KAJABI_API_CLIENT_SECRET", "").strip()
KAJABI_API_BASE = os.environ.get("KAJABI_API_BASE", "https://api.kajabi.com")
RECONCILE_INTERVAL_HOURS = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(a.encode()).digest(),
        hashlib.sha256(b.encode()).digest(),
    )


def _resource(payload: list[dict[str, Any]], type_name: str) -> Optional[dict]:
    return next((x for x in payload if x.get("type") == type_name), None)


class CancelBody(BaseModel):
    email: EmailStr
    # ISO 8601 date/datetime when the user's paid access should end. If
    # omitted, we cut off immediately.
    subscription_end_at: Optional[str] = None
    offer_id: Optional[str] = None


def create_kajabi_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(prefix="/kajabi", tags=["kajabi"])

    @router.post("/webhook")
    async def webhook(
        request: Request,
        token: Optional[str] = None,
        x_webhook_token: Optional[str] = Header(default=None),
    ):
        # Accept either ?token= query or X-Webhook-Token header. Kajabi's
        # webhook UI puts the whole URL in one field, so a query param is
        # the default; the header path is here in case we later route
        # through a proxy that strips or logs query strings.
        supplied = token or x_webhook_token or ""
        if not _constant_time_equal(supplied, KAJABI_WEBHOOK_TOKEN):
            raise HTTPException(status_code=401, detail="invalid_webhook_token")

        raw = await request.body()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid_json")

        event_name = body.get("event")
        event_id = str(body.get("id") or hashlib.sha256(raw).hexdigest())
        payload = body.get("payload") or []

        if not isinstance(event_name, str) or not isinstance(payload, list):
            raise HTTPException(status_code=400, detail="invalid_envelope")

        # Idempotency
        try:
            await db.webhook_events.insert_one({
                "provider": "kajabi",
                "external_event_id": event_id,
                "event": event_name,
                "received_at": _now_iso(),
                "body": body,
            })
        except DuplicateKeyError:
            return {"ok": True, "duplicate": True}

        purchase = _resource(payload, "purchases")
        customer = _resource(payload, "customers")
        offer = _resource(payload, "offers")
        transaction = _resource(payload, "transactions")

        customer_attrs = (customer or {}).get("attributes", {})
        offer_attrs = (offer or {}).get("attributes", {})
        purchase_attrs = (purchase or {}).get("attributes", {})
        transaction_attrs = (transaction or {}).get("attributes", {})

        email = (customer_attrs.get("email") or "").strip().lower()
        customer_id = (customer or {}).get("id")
        offer_id = (offer or {}).get("id") or (
            (purchase or {}).get("relationships", {})
            .get("offer", {}).get("data", {}) or {}
        ).get("id")

        if event_name in {"purchase", "payment_succeeded", "order_created"}:
            if email and offer_id:
                await db.memberships.update_one(
                    {"user_email": email, "offer_id": offer_id},
                    {"$set": {
                        "user_email": email,
                        "kajabi_customer_id": customer_id,
                        "offer_id": offer_id,
                        "offer_title": offer_attrs.get("title"),
                        "status": "active",
                        "subscription_end_at": None,
                        "last_event": event_name,
                        "last_payment_at": transaction_attrs.get("created_at")
                            or purchase_attrs.get("created_at")
                            or _now_iso(),
                        "updated_at": _now_iso(),
                    }},
                    upsert=True,
                )
                # If a user in our DB doesn't have an account yet (they
                # bought directly on Kajabi first), create a shell user
                # so login works instantly.
                await db.users.update_one(
                    {"email": email},
                    {"$setOnInsert": {
                        "email": email,
                        "trial_word_used": 0,
                        "trial_scene_used": 0,
                        "created_at": _now_iso(),
                        "last_login_at": None,
                    }},
                    upsert=True,
                )
                logger.info(f"Kajabi {event_name} → active: {email} / {offer_id}")
            else:
                logger.warning(f"Kajabi {event_name} missing email/offer_id")

        return {"ok": True}

    @router.post("/cancel")
    async def cancel(
        body: CancelBody,
        token: Optional[str] = None,
        x_webhook_token: Optional[str] = Header(default=None),
    ):
        """Kajabi Automation → HTTP action target for cancellations.

        Body must include `email` and (optionally) `subscription_end_at`
        (ISO 8601). We keep the row `active` until end_at passes; membership
        check consults this field before granting access.
        """
        supplied = token or x_webhook_token or ""
        if not _constant_time_equal(supplied, KAJABI_WEBHOOK_TOKEN):
            raise HTTPException(status_code=401, detail="invalid_webhook_token")

        email = body.email.strip().lower()
        end_at = body.subscription_end_at or _now_iso()
        q = {"user_email": email}
        if body.offer_id:
            q["offer_id"] = body.offer_id

        result = await db.memberships.update_many(
            q,
            {"$set": {
                "subscription_end_at": end_at,
                "last_event": "cancel",
                "updated_at": _now_iso(),
            }},
        )
        logger.info(f"Kajabi cancel → {email}, ends {end_at}, rows={result.modified_count}")
        return {"ok": True, "cancelled_rows": result.modified_count}

    @router.post("/admin/reconcile")
    async def admin_reconcile(
        token: Optional[str] = None,
        x_webhook_token: Optional[str] = Header(default=None),
    ):
        """Manually trigger a Kajabi ↔ DB membership reconciliation.

        Also runs automatically every 24h in the background (see the
        `start_reconciliation_loop` scheduler). Exposed here so we can
        (a) verify credentials, (b) trigger on demand for testing, and
        (c) recover quickly if the background loop dies.
        """
        supplied = token or x_webhook_token or ""
        if not _constant_time_equal(supplied, KAJABI_WEBHOOK_TOKEN):
            raise HTTPException(status_code=401, detail="invalid_webhook_token")
        result = await reconcile_memberships(db)
        return result

    return router


# --- Kajabi Public API client ----------------------------------------------
class _KajabiApi:
    """OAuth2 client_credentials client for the Kajabi Public API.

    Caches the access token in memory and refreshes ~1 min before expiry.
    """

    def __init__(self):
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _access_token(self) -> str:
        async with self._lock:
            now = time.time()
            if self._token and now < self._expires_at - 60:
                return self._token
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{KAJABI_API_BASE}/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": KAJABI_API_CLIENT_ID,
                        "client_secret": KAJABI_API_CLIENT_SECRET,
                    },
                )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"kajabi_oauth_failed:{r.status_code}:{r.text[:200]}"
                )
            data = r.json()
            self._token = data["access_token"]
            self._expires_at = now + int(data.get("expires_in", 3600))
            return self._token

    async def list_active_subscription_emails(self) -> tuple[set[str], list[dict]]:
        """Return (set of active-subscriber emails, list of raw sample records
        for debugging). Iterates purchases across pages and treats a purchase
        as active when it has no `deactivated_at` and its offer is flagged as
        a subscription (or the purchase status is 'active').
        """
        token = await self._access_token()
        active: set[str] = set()
        samples: list[dict] = []
        page = 1
        max_pages = 50   # 50 * 100 = 5000 records max per run — plenty for MVP
        async with httpx.AsyncClient(timeout=30.0) as client:
            while page <= max_pages:
                r = await client.get(
                    f"{KAJABI_API_BASE}/v1/purchases",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.api+json",
                    },
                    params={"page[size]": 100, "page[number]": page},
                )
                if r.status_code >= 400:
                    logger.error(
                        f"Kajabi list purchases page={page} failed: "
                        f"{r.status_code} {r.text[:300]}"
                    )
                    break
                doc = r.json()
                # Build customer id → email map from the `included` block.
                cust_by_id: dict[str, str] = {}
                for inc in doc.get("included", []) or []:
                    if inc.get("type") == "customers":
                        e = (inc.get("attributes", {}).get("email") or "").lower()
                        if e:
                            cust_by_id[inc.get("id")] = e
                for item in doc.get("data", []) or []:
                    attrs = item.get("attributes", {}) or {}
                    # Save a couple of raw records the first time through so
                    # we can inspect the response shape.
                    if len(samples) < 3:
                        samples.append({"id": item.get("id"), "attributes": attrs})
                    if attrs.get("deactivated_at"):
                        continue
                    status = str(attrs.get("status") or "").lower()
                    if status and status not in {"active", "in_trial", ""}:
                        continue
                    # Prefer email from attributes; fall back to included customers.
                    email = (attrs.get("email") or "").lower()
                    if not email:
                        rel_cust = (
                            (item.get("relationships") or {})
                            .get("member", {})
                            .get("data", {})
                            or {}
                        )
                        email = cust_by_id.get(rel_cust.get("id"), "").lower()
                    if email:
                        active.add(email)
                links = doc.get("links") or {}
                if not links.get("next"):
                    break
                page += 1
        return active, samples


_kajabi_api = _KajabiApi()


async def reconcile_memberships(db: AsyncIOMotorDatabase) -> dict:
    """Sync our memberships collection with Kajabi's active-purchase list.

    Any membership marked `active` in our DB but not returned by Kajabi's
    Public API as an active subscriber gets its `subscription_end_at`
    stamped to now (grace period ends immediately). Access is denied on
    the next request via _membership_status().

    Returns a JSON-friendly summary suitable for the admin endpoint.
    """
    if not KAJABI_API_CLIENT_ID or not KAJABI_API_CLIENT_SECRET:
        logger.info("reconcile_memberships: Kajabi API creds missing, skipping.")
        return {"ok": False, "skipped": "missing_credentials"}

    try:
        active_emails, samples = await _kajabi_api.list_active_subscription_emails()
    except Exception as exc:
        logger.exception(f"reconcile_memberships fetch failed: {exc}")
        return {"ok": False, "error": str(exc)[:200]}

    now = _now_iso()
    cursor = db.memberships.find({"status": "active"})
    checked = 0
    cancelled = 0
    async for m in cursor:
        checked += 1
        email = (m.get("user_email") or "").lower()
        if email in active_emails:
            continue
        # Already scheduled for termination? Leave alone.
        if m.get("subscription_end_at"):
            continue
        await db.memberships.update_one(
            {"_id": m["_id"]},
            {"$set": {
                "subscription_end_at": now,
                "last_event": "reconcile_cancel",
                "updated_at": now,
            }},
        )
        cancelled += 1
        logger.info(f"reconcile: cancelled {email}")
    logger.info(
        f"reconcile complete: checked={checked} cancelled={cancelled} "
        f"active_on_kajabi={len(active_emails)}"
    )
    return {
        "ok": True,
        "checked": checked,
        "cancelled": cancelled,
        "active_on_kajabi": len(active_emails),
        "samples": samples,
    }


async def _reconciliation_loop(db: AsyncIOMotorDatabase):
    """Long-running background task that reconciles every RECONCILE_INTERVAL_HOURS.

    Sleeps first so we don't hammer Kajabi during app boot. If a run fails,
    we still wait the full interval before the next attempt — the manual
    /admin/reconcile endpoint is available for immediate recovery.
    """
    # Small startup delay so this doesn't compete with cold-start traffic.
    await asyncio.sleep(60)
    while True:
        try:
            await reconcile_memberships(db)
        except Exception as exc:
            logger.exception(f"reconciliation loop iteration failed: {exc}")
        await asyncio.sleep(RECONCILE_INTERVAL_HOURS * 3600)


def start_reconciliation_loop(db: AsyncIOMotorDatabase) -> asyncio.Task:
    """Kick off the background reconciliation loop. Call once from startup."""
    return asyncio.create_task(_reconciliation_loop(db))
