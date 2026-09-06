"""Owner admin panel — for manually managing memberships without a
Kajabi Pro subscription (which the Public API requires).

Access: gated to emails listed in the `ADMIN_EMAILS` env var
(comma-separated). Every route uses `require_admin` from auth.py.

Endpoints:
    GET  /admin/whoami                 - is the caller an admin?
    GET  /admin/memberships            - list all memberships (search + status filter)
    POST /admin/memberships/cancel     - end a member's access at a specified date
    POST /admin/memberships/grant      - manually grant access to an email
                                         (group coaching students, refunds, comps)
    GET  /admin/users                  - list users with trial + membership summary
    GET  /admin/events                 - last 50 webhook events for debugging
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr

from auth import require_admin
from stripe_payments import sync_from_stripe_customer


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
                       "audio/webm", "audio/ogg", "audio/mp4", "audio/m4a"}
MAX_AUDIO_BYTES = 2 * 1024 * 1024   # 2 MB is plenty for a single word


class CancelBody(BaseModel):
    email: EmailStr
    # Optional ISO date/time to end access. If omitted, access ends immediately
    # (rare — usually you'll want to honor their paid-through date).
    subscription_end_at: Optional[str] = None


class GrantBody(BaseModel):
    email: EmailStr
    offer_title: str = "Manual grant"
    # How many days from now to expire the grant. 0 or omitted = no expiry
    # (permanent, e.g., for a group-coaching student).
    days: int = 0


class DeleteOverrideBody(BaseModel):
    word: str


class StripeSyncBody(BaseModel):
    email: EmailStr


def create_admin_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/whoami")
    async def whoami(request: Request):
        email = await require_admin(request, db)
        return {"admin": True, "email": email}

    @router.get("/memberships")
    async def list_memberships(
        request: Request,
        q: Optional[str] = None,
        status: Optional[str] = None,   # "active" | "cancelled" | "all"
        limit: int = 100,
    ):
        await require_admin(request, db)
        query: dict = {}
        if status == "active":
            # An "active" membership either has no end date or the end
            # date is still in the future.
            now = _now_iso()
            query = {
                "status": "active",
                "$or": [
                    {"subscription_end_at": None},
                    {"subscription_end_at": {"$gt": now}},
                ],
            }
        elif status == "cancelled":
            now = _now_iso()
            query = {
                "$or": [
                    {"status": {"$ne": "active"}},
                    {"subscription_end_at": {"$lte": now, "$ne": None}},
                ],
            }
        if q:
            query["user_email"] = {"$regex": q.lower(), "$options": "i"}
        docs = await (
            db.memberships.find(query, {"_id": 0})
            .sort("updated_at", -1)
            .to_list(min(limit, 500))
        )
        return {"count": len(docs), "memberships": docs}

    @router.post("/memberships/cancel")
    async def cancel_membership(body: CancelBody, request: Request):
        await require_admin(request, db)
        email = body.email.strip().lower()
        end_at = body.subscription_end_at or _now_iso()
        result = await db.memberships.update_many(
            {"user_email": email},
            {"$set": {
                "subscription_end_at": end_at,
                "last_event": "admin_cancel",
                "updated_at": _now_iso(),
            }},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="no_membership_found")
        return {
            "ok": True,
            "cancelled_rows": result.modified_count,
            "subscription_end_at": end_at,
        }

    @router.post("/memberships/grant")
    async def grant_membership(body: GrantBody, request: Request):
        await require_admin(request, db)
        email = body.email.strip().lower()
        end_at: Optional[str] = _in_days(body.days) if body.days > 0 else None
        # Auto-create the user shell if they haven't logged in yet — that
        # way they can log in with a magic link and hit the app immediately.
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
        await db.memberships.update_one(
            {"user_email": email, "offer_id": "manual_grant"},
            {"$set": {
                "user_email": email,
                "kajabi_customer_id": None,
                "offer_id": "manual_grant",
                "offer_title": body.offer_title,
                "status": "active",
                "subscription_end_at": end_at,
                "last_event": "admin_grant",
                "last_payment_at": _now_iso(),
                "updated_at": _now_iso(),
            }},
            upsert=True,
        )
        return {"ok": True, "email": email, "subscription_end_at": end_at}

    @router.get("/users")
    async def list_users(
        request: Request,
        q: Optional[str] = None,
        limit: int = 100,
    ):
        await require_admin(request, db)
        query: dict = {}
        if q:
            query["email"] = {"$regex": q.lower(), "$options": "i"}
        users = await (
            db.users.find(query, {"_id": 0})
            .sort("created_at", -1)
            .to_list(min(limit, 500))
        )
        # Attach a quick membership summary per user.
        emails = [u["email"] for u in users]
        memberships = await db.memberships.find(
            {"user_email": {"$in": emails}}, {"_id": 0}
        ).to_list(1000)
        by_email: dict[str, dict] = {}
        now = _now_iso()
        for m in memberships:
            e = m["user_email"]
            ends = m.get("subscription_end_at")
            is_active = m.get("status") == "active" and (
                not ends or ends > now
            )
            prev = by_email.get(e)
            if not prev or (is_active and not prev.get("is_active")):
                by_email[e] = {
                    "offer_title": m.get("offer_title"),
                    "is_active": is_active,
                    "subscription_end_at": ends,
                }
        for u in users:
            u["membership"] = by_email.get(u["email"])
        return {"count": len(users), "users": users}

    @router.get("/events")
    async def recent_events(request: Request, limit: int = 50):
        await require_admin(request, db)
        docs = await (
            db.webhook_events.find({}, {"_id": 0, "body": 0})
            .sort("received_at", -1)
            .to_list(min(limit, 200))
        )
        return {"count": len(docs), "events": docs}

    # --- Manual pronunciation overrides ---------------------------------
    # For words ElevenLabs mispronounces (proper nouns like "Los Angeles",
    # actor names, technical terms). Katherine records the correct
    # pronunciation once; it's saved into the shared `audio_cache`
    # collection and served on every future /api/tts call for that word,
    # bypassing ElevenLabs entirely.

    @router.get("/pronunciation-overrides")
    async def list_pronunciation_overrides(request: Request, limit: int = 100):
        await require_admin(request, db)
        docs = await (
            db.audio_cache.find(
                {"manual_override": True},
                {"_id": 0, "audio_b64": 0},  # strip the giant base64
            )
            .sort("created_at", -1)
            .to_list(min(limit, 500))
        )
        return {"count": len(docs), "overrides": docs}

    @router.post("/pronunciation-overrides")
    async def upload_pronunciation_override(
        request: Request,
        word: str = Form(...),
        file: UploadFile = File(...),
    ):
        await require_admin(request, db)
        clean_word = word.strip().lower()
        if not clean_word:
            raise HTTPException(status_code=400, detail="word_required")

        # Read + validate size (multipart uploads have no reliable
        # Content-Length by the time they reach us).
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="empty_file")
        if len(raw) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="file_too_large_max_2mb")
        ct = (file.content_type or "").lower()
        if ct and ct not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(status_code=400,
                                detail=f"unsupported_audio_type:{ct}")

        audio_b64 = base64.b64encode(raw).decode("ascii")
        await db.audio_cache.update_one(
            {"word": clean_word},
            {"$set": {
                "word": clean_word,
                "audio_b64": audio_b64,
                "manual_override": True,
                "content_type": ct or "audio/mpeg",
                "byte_size": len(raw),
                "created_at": _now_iso(),
            }},
            upsert=True,
        )
        return {
            "ok": True,
            "word": clean_word,
            "byte_size": len(raw),
            "content_type": ct or "audio/mpeg",
        }

    @router.post("/pronunciation-overrides/delete")
    async def delete_pronunciation_override(
        body: DeleteOverrideBody, request: Request
    ):
        await require_admin(request, db)
        clean_word = body.word.strip().lower()
        if not clean_word:
            raise HTTPException(status_code=400, detail="word_required")
        result = await db.audio_cache.delete_one(
            {"word": clean_word, "manual_override": True}
        )
        return {"ok": True, "deleted": result.deleted_count}

    @router.post("/stripe/sync")
    async def stripe_sync(body: StripeSyncBody, request: Request):
        """Admin utility: force resync a user's memberships from Stripe.

        Solves the "Stripe shows Active but app shows Free Trial" edge case
        by pulling the current subscription state directly from Stripe
        (bypassing webhook delivery). Idempotent.
        """
        await require_admin(request, db)
        result = await sync_from_stripe_customer(db, body.email.strip().lower())
        return result

    return router
