"""Stripe subscription routes for Accent Coach.

Endpoints (all under /api):
    POST /payments/checkout      - create a Stripe Checkout session for a lookup_key
    GET  /payments/status/{sid}  - unauth polling of a checkout session's payment status
    POST /payments/portal        - one-tap Stripe Customer Portal URL (cancel / manage card / upgrade)
    POST /stripe/webhook         - Stripe webhook receiver (signed)

Design:
    - Two subscription prices are configured via lookup_key so we never hardcode
      Stripe price IDs. See `setup_stripe.py` for the catalog.
    - The frontend requests a checkout by lookup_key + origin_url; we build the
      redirect URLs server-side.
    - On successful checkout, we upsert a row in the shared `memberships`
      collection so the same access-check code that powers Kajabi-granted users
      works for Stripe-paying users too.
    - Access ends via subscription.deleted (Stripe honours the paid-through
      date automatically by only firing deleted at cycle end for cancellations).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import APIRouter, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from auth import require_login

logger = logging.getLogger(__name__)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or "sk_test_emergent"
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckoutRequest(BaseModel):
    lookup_key: str = Field(..., pattern=r"^[a-z0-9_]+$")
    origin_url: str


class PortalRequest(BaseModel):
    origin_url: str


def create_stripe_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(tags=["stripe"])

    async def _get_or_create_customer(email: str) -> str:
        """Return the Stripe customer ID for this user, creating one if needed."""
        user = await db.users.find_one({"email": email})
        cust_id = (user or {}).get("stripe_customer_id")
        if cust_id:
            return cust_id
        cust = stripe.Customer.create(email=email, metadata={"app_user_email": email})
        await db.users.update_one(
            {"email": email},
            {"$set": {"stripe_customer_id": cust.id, "updated_at": _now_iso()}},
        )
        return cust.id

    @router.post("/payments/checkout")
    async def create_checkout(body: CheckoutRequest, request: Request):
        email = await require_login(request, db)
        prices = stripe.Price.list(
            lookup_keys=[body.lookup_key], active=True, limit=1
        ).data
        if not prices:
            raise HTTPException(400, f"unknown_price:{body.lookup_key}")
        price = prices[0]
        if not price.recurring:
            raise HTTPException(400, "price_not_recurring")

        customer_id = await _get_or_create_customer(email)
        session = stripe.checkout.Session.create(
            customer=customer_id,
            line_items=[{"price": price.id, "quantity": 1}],
            mode="subscription",
            success_url=(
                f"{body.origin_url.rstrip('/')}/payment/success"
                "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{body.origin_url.rstrip('/')}/payment/cancel",
            client_reference_id=email,
            metadata={"app_user_email": email, "lookup_key": body.lookup_key},
            subscription_data={
                "metadata": {"app_user_email": email, "lookup_key": body.lookup_key},
            },
            allow_promotion_codes=True,
        )
        await db.payment_transactions.insert_one({
            "session_id": session.id,
            "email": email,
            "lookup_key": body.lookup_key,
            "amount": (price.unit_amount or 0),
            "currency": price.currency,
            "status": "initiated",
            "payment_status": "pending",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        return {"checkout_url": session.url, "session_id": session.id}

    @router.get("/payments/status/{session_id}")
    async def get_status(session_id: str):
        """Unauthenticated status poll — returns only the session state so a
        just-completed checkout can flip the UI to authenticated-subscriber."""
        record = await db.payment_transactions.find_one({"session_id": session_id})
        if not record:
            raise HTTPException(404, "not_found")
        if record.get("payment_status") != "paid":
            try:
                s = stripe.checkout.Session.retrieve(session_id)
                if s.payment_status == "paid" or s.status == "complete":
                    await db.payment_transactions.update_one(
                        {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                        {"$set": {
                            "status": "completed",
                            "payment_status": "paid",
                            "stripe_subscription_id": s.subscription,
                            "updated_at": _now_iso(),
                        }},
                    )
                    # Also flip membership immediately so the app's /me poll
                    # returns is_subscriber before the webhook lands.
                    await _grant_from_session(db, s)
                    record = await db.payment_transactions.find_one(
                        {"session_id": session_id}
                    )
            except stripe.error.StripeError as exc:
                logger.warning(f"stripe retrieve failed for {session_id}: {exc}")
        return {
            "session_id": record["session_id"],
            "status": record["status"],
            "payment_status": record["payment_status"],
        }

    @router.post("/payments/portal")
    async def create_portal(body: PortalRequest, request: Request):
        email = await require_login(request, db)
        user = await db.users.find_one({"email": email})
        cust_id = (user or {}).get("stripe_customer_id")
        if not cust_id:
            raise HTTPException(400, "no_stripe_customer")
        portal = stripe.billing_portal.Session.create(
            customer=cust_id,
            return_url=body.origin_url.rstrip("/"),
        )
        return {"url": portal.url}

    @router.post("/stripe/webhook")
    async def stripe_webhook(request: Request):
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig, STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError) as exc:
            logger.warning(f"stripe webhook signature failed: {exc}")
            raise HTTPException(400, "bad_signature")

        # Idempotency
        try:
            await db.webhook_events.insert_one({
                "provider": "stripe",
                "external_event_id": event["id"],
                "event": event["type"],
                "received_at": _now_iso(),
                "body": event.to_dict() if hasattr(event, "to_dict") else dict(event),
            })
        except DuplicateKeyError:
            return {"ok": True, "duplicate": True}

        obj = event["data"]["object"]
        t = event["type"]

        if t == "checkout.session.completed":
            await db.payment_transactions.update_one(
                {"session_id": obj["id"], "payment_status": {"$ne": "paid"}},
                {"$set": {
                    "status": "completed",
                    "payment_status": obj.get("payment_status", "paid"),
                    "stripe_subscription_id": obj.get("subscription"),
                    "updated_at": _now_iso(),
                }},
            )
            await _grant_from_session(db, obj)

        elif t in ("customer.subscription.updated", "customer.subscription.created"):
            await _sync_subscription(db, obj)

        elif t == "customer.subscription.deleted":
            # Fired when the subscription actually ends (after cancel-at-
            # period-end has been honoured, or on immediate cancellation).
            await _mark_cancelled(db, obj)

        elif t == "invoice.payment_failed":
            logger.warning(
                f"stripe invoice.payment_failed: customer={obj.get('customer')} "
                f"sub={obj.get('subscription')}"
            )
            # Access remains until subscription.deleted; Stripe's dunning will
            # retry and either recover or cancel.

        return {"ok": True}

    return router


# --- Membership sync helpers ------------------------------------------------
def _lookup_key_to_title(lookup_key: str) -> str:
    return {
        "accent_coach_monthly": "American Accent Prep — Monthly",
        "accent_coach_yearly": "American Accent Prep — Annual",
    }.get(lookup_key, "American Accent Prep")


async def _grant_from_session(db: AsyncIOMotorDatabase, session) -> None:
    """Given a Stripe Checkout Session (subscription mode), flip the user's
    membership to active. Called from both /status poll (as a fallback) and
    the checkout.session.completed webhook."""
    email = (
        (session.get("metadata") or {}).get("app_user_email")
        or session.get("client_reference_id")
        or ""
    ).strip().lower()
    if not email:
        logger.warning("checkout.session missing email metadata")
        return
    sub_id = session.get("subscription")
    lookup_key = (session.get("metadata") or {}).get("lookup_key", "")
    offer_title = _lookup_key_to_title(lookup_key)

    # Auto-create the user shell if they somehow don't have one yet
    # (shouldn't happen — checkout requires login — but defensive).
    await db.users.update_one(
        {"email": email},
        {"$setOnInsert": {
            "email": email,
            "trial_word_used": 0,
            "trial_scene_used": 0,
            "created_at": _now_iso(),
            "last_login_at": None,
        },
         "$set": {"stripe_customer_id": session.get("customer")}},
        upsert=True,
    )
    await db.memberships.update_one(
        {"user_email": email, "offer_id": f"stripe:{lookup_key}"},
        {"$set": {
            "user_email": email,
            "kajabi_customer_id": None,
            "stripe_customer_id": session.get("customer"),
            "stripe_subscription_id": sub_id,
            "offer_id": f"stripe:{lookup_key}",
            "offer_title": offer_title,
            "status": "active",
            "subscription_end_at": None,
            "last_event": "checkout_completed",
            "last_payment_at": _now_iso(),
            "updated_at": _now_iso(),
        }},
        upsert=True,
    )
    logger.info(f"stripe → active: {email} / {lookup_key}")


async def _sync_subscription(db: AsyncIOMotorDatabase, sub) -> None:
    """Reflect a customer.subscription.updated/created into memberships.

    If the sub is scheduled to cancel at period end, we stamp
    `subscription_end_at` so the access gate honours it.
    """
    metadata = sub.get("metadata") or {}
    email = (metadata.get("app_user_email") or "").strip().lower()
    if not email:
        # Look up by customer if metadata wasn't propagated.
        cust = await db.users.find_one({"stripe_customer_id": sub.get("customer")})
        email = (cust or {}).get("email", "").strip().lower()
    if not email:
        logger.warning(f"subscription {sub.get('id')} has no linkable email")
        return

    lookup_key = metadata.get("lookup_key", "")
    status = sub.get("status")   # active | trialing | past_due | canceled | ...
    cancel_at = sub.get("cancel_at")  # int unix seconds if scheduled
    subscription_end_at: Optional[str] = None
    if cancel_at:
        subscription_end_at = datetime.fromtimestamp(
            cancel_at, tz=timezone.utc
        ).isoformat()

    is_active = status in ("active", "trialing")
    await db.memberships.update_one(
        {"user_email": email, "offer_id": f"stripe:{lookup_key}"},
        {"$set": {
            "user_email": email,
            "stripe_subscription_id": sub.get("id"),
            "offer_id": f"stripe:{lookup_key}",
            "offer_title": _lookup_key_to_title(lookup_key),
            "status": "active" if is_active else "cancelled",
            "subscription_end_at": subscription_end_at,
            "last_event": f"sub_{status}",
            "updated_at": _now_iso(),
        }},
        upsert=True,
    )
    logger.info(f"stripe sub sync: {email} status={status} end={subscription_end_at}")


async def _mark_cancelled(db: AsyncIOMotorDatabase, sub) -> None:
    """subscription.deleted → the subscription has fully ended. Cut access now."""
    sub_id = sub.get("id")
    result = await db.memberships.update_many(
        {"stripe_subscription_id": sub_id},
        {"$set": {
            "subscription_end_at": _now_iso(),
            "last_event": "sub_deleted",
            "updated_at": _now_iso(),
        }},
    )
    logger.info(f"stripe subscription.deleted {sub_id} → rows={result.modified_count}")
