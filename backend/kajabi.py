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

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

KAJABI_WEBHOOK_TOKEN = os.environ["KAJABI_WEBHOOK_TOKEN"]


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

    return router
