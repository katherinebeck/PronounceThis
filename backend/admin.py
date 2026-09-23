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
import csv
import io
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr

from auth import require_admin
from phonetics import (
    PREFERRED_ARPA, arpabet_to_ipa, classify_word, cmu_variants, transcribe_word,
    validate_arpabet,
)
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


class MagicLinkBody(BaseModel):
    email: EmailStr


class DeleteUserBody(BaseModel):
    email: EmailStr


class SetEndBody(BaseModel):
    email: EmailStr
    subscription_end_at: Optional[str] = None   # "YYYY-MM-DD" or null = no end


class HideVideoBody(BaseModel):
    url_or_id: str
    reason: Optional[str] = None


class UnhideVideoBody(BaseModel):
    video_id: str


class DismissWordBody(BaseModel):
    word: str


class AssignSceneBody(BaseModel):
    scene_id: str
    email: EmailStr


class PronunciationPrefBody(BaseModel):
    word: str
    arpabet: str   # e.g. "B IH0 K AH1 Z"


class PronunciationPrefDeleteBody(BaseModel):
    word: str


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

    @router.post("/memberships/set-end")
    async def set_membership_end(body: SetEndBody, request: Request):
        """Adjust when a manually granted membership ends (extend or shorten).
        Creates the grant if the user has none yet."""
        await require_admin(request, db)
        email = body.email.strip().lower()
        end_at: Optional[str] = None
        if body.subscription_end_at:
            try:
                d = datetime.fromisoformat(body.subscription_end_at[:10])
            except ValueError:
                raise HTTPException(status_code=400, detail="bad_date_use_YYYY-MM-DD")
            end_at = d.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc).isoformat()
        existing = await db.memberships.find_one(
            {"user_email": email}, sort=[("offer_id", -1)])
        target = {"user_email": email, "offer_id": "manual_grant"}
        if existing and existing.get("offer_id") != "manual_grant" and existing.get("stripe_subscription_id"):
            raise HTTPException(
                status_code=400,
                detail="stripe_membership_edit_in_stripe: this member pays via Stripe — change their subscription there")
        await db.memberships.update_one(
            target,
            {"$set": {**target, "status": "active", "subscription_end_at": end_at,
                      "offer_title": (existing or {}).get("offer_title") or "Complimentary access",
                      "last_event": "admin_set_end", "updated_at": _now_iso()},
             "$setOnInsert": {"kajabi_customer_id": None, "last_payment_at": _now_iso()}},
            upsert=True,
        )
        return {"ok": True, "email": email, "subscription_end_at": end_at}

    @router.get("/users")
    async def list_users(
        request: Request,
        q: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
    ):
        await require_admin(request, db)
        limit = max(1, min(limit, 100))
        page = max(1, page)
        query: dict = {}
        if q:
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            # Match on email, or on a membership's offer/plan title (name-ish).
            member_emails = await db.memberships.distinct(
                "user_email", {"offer_title": rx}
            )
            query["$or"] = [{"email": rx}, {"email": {"$in": member_emails}}]
        total = await db.users.count_documents(query)
        users = await (
            db.users.find(query, {"_id": 0})
            .sort("created_at", -1)
            .skip((page - 1) * limit)
            .limit(limit)
            .to_list(limit)
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
        return {"count": len(users), "total": total, "page": page,
                "limit": limit, "users": users}

    # --- Data export (CSV) ----------------------------------------------
    USER_COLS = ["email", "created_at", "last_login_at", "stripe_customer_id",
                 "trial_word_used", "trial_scene_used", "last_stripe_sync_at"]
    MEMBERSHIP_COLS = ["user_email", "offer_id", "offer_title", "status",
                       "subscription_end_at", "stripe_customer_id",
                       "stripe_subscription_id", "kajabi_customer_id",
                       "last_event", "last_payment_at", "updated_at"]

    def _csv_response(rows: list, cols: list, filename: str) -> Response:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/export/users.csv")
    async def export_users_csv(request: Request):
        await require_admin(request, db)
        rows = await db.users.find({}, {"_id": 0}).sort("created_at", 1).to_list(100_000)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return _csv_response(rows, USER_COLS, f"users-{stamp}.csv")

    @router.get("/export/memberships.csv")
    async def export_memberships_csv(request: Request):
        await require_admin(request, db)
        rows = await db.memberships.find({}, {"_id": 0}).sort("updated_at", 1).to_list(100_000)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return _csv_response(rows, MEMBERSHIP_COLS, f"memberships-{stamp}.csv")

    @router.post("/users/delete")
    async def delete_user(body: DeleteUserBody, request: Request):
        """Remove a user entirely: account, memberships, pending magic links.
        Their Stripe customer (if any) is untouched — cancel that in Stripe."""
        admin_email = await require_admin(request, db)
        email = body.email.strip().lower()
        if email == admin_email:
            raise HTTPException(status_code=400, detail="cannot_delete_yourself")
        u = await db.users.delete_one({"email": email})
        m = await db.memberships.delete_many({"user_email": email})
        ml = await db.magic_links.delete_many({"email": email})
        if u.deleted_count == 0 and m.deleted_count == 0:
            raise HTTPException(status_code=404, detail="user_not_found")
        return {"ok": True, "email": email, "users": u.deleted_count,
                "memberships": m.deleted_count, "magic_links": ml.deleted_count}

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
        ct = (file.content_type or "").lower().split(";")[0].strip()
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

    # --- Preferred pronunciations (dictionary-level, no recording) -------
    def _clean_word(w: str) -> str:
        import re as _re
        return _re.sub(r"[^a-z']", "", (w or "").lower().strip())

    async def _invalidate_audio(w: str) -> None:
        import re as _re
        await db.audio_cache.delete_many(
            {"word": {"$in": [w, f"{w}#ph"]}, "manual_override": {"$ne": True}})
        # Scene lines that contain the word regenerate on next play.
        await db.turn_audio_cache.delete_many(
            {"text": {"$regex": rf"\b{_re.escape(w)}\b", "$options": "i"}})

    @router.get("/pronunciations")
    async def list_pronunciation_prefs(request: Request):
        await require_admin(request, db)
        docs = await db.pronunciation_prefs.find({}, {"_id": 0}).sort("word", 1).to_list(1000)
        return {"count": len(docs), "prefs": docs}

    @router.get("/pronunciations/options")
    async def pronunciation_options(request: Request, word: str,
                                    arpabet: Optional[str] = None):
        """CMU variants for a word (with IPA), plus a preview of a custom
        ARPABET string if supplied."""
        await require_admin(request, db)
        w = _clean_word(word)
        if not w:
            raise HTTPException(status_code=400, detail="word_required")
        variants = [{"arpabet": " ".join(v), "ipa": arpabet_to_ipa(v)}
                    for v in cmu_variants(w)]
        current = PREFERRED_ARPA.get(w)
        out: dict = {
            "word": w,
            "variants": variants,
            "current": {"arpabet": current,
                        "ipa": arpabet_to_ipa(current.split())} if current else None,
        }
        if arpabet is not None:
            phones = validate_arpabet(arpabet)
            out["preview"] = ({"arpabet": " ".join(phones), "ipa": arpabet_to_ipa(phones)}
                              if phones else None)
        return out

    @router.post("/pronunciations")
    async def set_pronunciation_pref(body: PronunciationPrefBody, request: Request):
        await require_admin(request, db)
        w = _clean_word(body.word)
        phones = validate_arpabet(body.arpabet)
        if not w:
            raise HTTPException(status_code=400, detail="word_required")
        if not phones:
            raise HTTPException(
                status_code=400,
                detail="invalid_arpabet: use CMU phones, vowels need stress 0/1/2 (e.g. B IH0 K AH1 Z)")
        arp = " ".join(phones)
        await db.pronunciation_prefs.update_one(
            {"word": w},
            {"$set": {"word": w, "arpabet": arp, "ipa": arpabet_to_ipa(phones),
                      "categories": classify_word(phones), "updated_at": _now_iso()}},
            upsert=True,
        )
        PREFERRED_ARPA[w] = arp
        # Drop generated audio so the next play follows the new pronunciation.
        await _invalidate_audio(w)
        return {"ok": True, "word": w, "arpabet": arp, "ipa": arpabet_to_ipa(phones)}

    @router.post("/pronunciations/delete")
    async def delete_pronunciation_pref(body: PronunciationPrefDeleteBody, request: Request):
        await require_admin(request, db)
        w = _clean_word(body.word)
        res = await db.pronunciation_prefs.delete_one({"word": w})
        PREFERRED_ARPA.pop(w, None)
        await _invalidate_audio(w)
        return {"ok": True, "deleted": res.deleted_count}

    # --- Hidden Real-Speakers videos ------------------------------------
    def _extract_video_id(text: str) -> Optional[str]:
        import re as _re
        t = (text or "").strip()
        m = (_re.search(r"[?&]v=([A-Za-z0-9_-]{11})", t)
             or _re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", t)
             or _re.search(r"/(?:embed|shorts)/([A-Za-z0-9_-]{11})", t)
             or _re.fullmatch(r"([A-Za-z0-9_-]{11})", t))
        return m.group(1) if m else None

    @router.get("/hidden-videos")
    async def list_hidden_videos(request: Request):
        await require_admin(request, db)
        docs = await db.hidden_videos.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
        return {"count": len(docs), "videos": docs}

    @router.post("/hidden-videos")
    async def hide_video(body: HideVideoBody, request: Request):
        await require_admin(request, db)
        vid = _extract_video_id(body.url_or_id)
        if not vid:
            raise HTTPException(status_code=400, detail="could_not_parse_video_id")
        meta = await db.caption_transcript_cache.find_one(
            {"video_id": vid}, {"_id": 0, "channel_meta": 1})
        cm = (meta or {}).get("channel_meta") or {}
        await db.hidden_videos.update_one(
            {"video_id": vid},
            {"$set": {"video_id": vid, "reason": (body.reason or "").strip(),
                      "title": cm.get("title", ""), "channel_title": cm.get("channel_title", ""),
                      "created_at": _now_iso()}},
            upsert=True,
        )
        from server import caption_service
        caption_service.invalidate_hidden()
        return {"ok": True, "video_id": vid}

    @router.post("/hidden-videos/delete")
    async def unhide_video(body: UnhideVideoBody, request: Request):
        await require_admin(request, db)
        res = await db.hidden_videos.delete_one({"video_id": body.video_id})
        from server import caption_service
        caption_service.invalidate_hidden()
        return {"ok": True, "deleted": res.deleted_count}

    # --- Scenes: legacy (unowned) + manual assignment ----------------------
    @router.get("/scenes")
    async def admin_list_scenes(request: Request, unowned_only: bool = True, limit: int = 500):
        await require_admin(request, db)
        q = {"owner_email": None} if unowned_only else {}
        cursor = db.scenes.find(q, {"_id": 0, "id": 1, "title": 1, "created_at": 1,
                                    "owner_email": 1, "legacy": 1, "tokens": 1}).sort("created_at", -1)
        out = []
        async for s in cursor.to_list(limit) if False else cursor:
            out.append({
                "id": s["id"], "title": s.get("title", ""), "created_at": s.get("created_at"),
                "owner_email": s.get("owner_email"), "legacy": bool(s.get("legacy")),
                "word_count": sum(1 for t in s.get("tokens", []) if t.get("is_word")),
            })
            if len(out) >= limit:
                break
        return {"count": len(out), "scenes": out}

    @router.post("/scenes/assign")
    async def admin_assign_scene(body: AssignSceneBody, request: Request):
        """Give a legacy/unowned scene to a user (admin-verified ownership)."""
        admin_email = await require_admin(request, db)
        email = body.email.strip().lower()
        if not await db.users.find_one({"email": email}, {"_id": 0, "email": 1}):
            raise HTTPException(status_code=404, detail="user_not_found")
        res = await db.scenes.update_one(
            {"id": body.scene_id},
            {"$set": {"owner_email": email, "legacy": False,
                      "assigned_by": admin_email, "assigned_at": _now_iso()}},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="scene_not_found")
        return {"ok": True, "scene_id": body.scene_id, "owner_email": email}

    # --- Recording queue --------------------------------------------------
    @router.get("/recording-queue")
    async def recording_queue(request: Request, limit: int = 100):
        """Words students have played as synthetic audio (no human
        recording yet), most-played first."""
        await require_admin(request, db)
        overrides = {d["word"] for d in await db.audio_cache.find(
            {"manual_override": True}, {"_id": 0, "word": 1}).to_list(10000)}
        docs = await db.tts_log.find(
            {"dismissed": {"$ne": True}}, {"_id": 0}
        ).sort([("count", -1), ("last_at", -1)]).to_list(limit * 3)
        out = []
        for d in docs:
            w = d["word"]
            if w in overrides:
                continue
            ipa, _, _ = transcribe_word(w.replace(" ", ""))
            out.append({"word": w, "count": d.get("count", 0),
                        "last_at": d.get("last_at"), "ipa": ipa,
                        "phonetic": bool(d.get("phonetic"))})
            if len(out) >= limit:
                break
        return {"count": len(out), "words": out}

    @router.post("/recording-queue/dismiss")
    async def dismiss_recording(body: DismissWordBody, request: Request):
        await require_admin(request, db)
        await db.tts_log.update_one(
            {"word": body.word.strip().lower()}, {"$set": {"dismissed": True}})
        return {"ok": True}

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

    @router.post("/magic-link")
    async def issue_magic_link(body: MagicLinkBody, request: Request):
        """Admin utility: mint a one-time sign-in URL for a student and
        return it (no email sent). Handy for in-person lessons or hand-offs
        where the coach wants to log the student in without waiting on
        Resend delivery.

        Behaves exactly like the public /auth/request-magic-link path, but
        returns the URL directly. Link expires in 15 minutes and is
        single-use, same as an emailed link.
        """
        await require_admin(request, db)
        email = body.email.strip().lower()

        # Auto-create the user shell so the link lands them in a valid
        # session on first click.
        now = datetime.now(timezone.utc)
        await db.users.update_one(
            {"email": email},
            {"$setOnInsert": {
                "email": email,
                "trial_word_used": 0,
                "trial_scene_used": 0,
                "created_at": now.isoformat(),
                "last_login_at": None,
            }},
            upsert=True,
        )

        token = secrets.token_urlsafe(32)
        # Admin-issued links don't expire (still single-use): the student
        # may open the email days later for their first sign-in.
        expires_at = now + timedelta(days=3650)
        await db.magic_links.insert_one({
            "token": token,
            "email": email,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "expires_at_dt": expires_at,
            "consumed": False,
            "source": "admin_issued",
        })

        # Build the sign-in URL from the request's origin so the link works
        # on whatever domain the admin is signed in from (preview or prod).
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            from urllib.parse import urlparse
            u = urlparse(origin)
            base = f"{u.scheme}://{u.netloc}"
        else:
            base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
        login_url = f"{base}/auth/verify?token={token}"

        return {
            "ok": True,
            "email": email,
            "login_url": login_url,
            "expires_at": None,
            "single_use": True,
        }

    @router.get("/debug/user")
    async def debug_user(request: Request, email: str):
        """Admin diagnostic — dumps everything we know about one user across
        our DB and Stripe. Used to figure out why a paying customer isn't
        being recognized as a member."""
        import json
        import stripe
        await require_admin(request, db)
        email = email.strip().lower()

        def _stripe_to_dict(obj):
            if obj is None:
                return None
            try:
                return json.loads(str(obj))
            except Exception:
                return {"_repr": repr(obj)[:200]}

        user = await db.users.find_one({"email": email}, {"_id": 0})
        memberships = await db.memberships.find(
            {"user_email": email}, {"_id": 0}
        ).to_list(20)
        magic_links_count = await db.magic_links.count_documents({"email": email})

        # Stripe: look up customer by stored id + by email, list their subs.
        stripe_info = {"customer_by_stored_id": None,
                       "customers_by_email": [], "subscriptions": []}
        try:
            stored_cust_id = (user or {}).get("stripe_customer_id")
            if stored_cust_id:
                try:
                    c = _stripe_to_dict(stripe.Customer.retrieve(stored_cust_id))
                    stripe_info["customer_by_stored_id"] = {
                        "id": c.get("id"), "email": c.get("email"),
                        "deleted": c.get("deleted"),
                    }
                except Exception as exc:
                    stripe_info["customer_by_stored_id_error"] = f"{type(exc).__name__}: {exc}"
            by_email_raw = stripe.Customer.list(email=email, limit=5).data
            by_email = [_stripe_to_dict(c) for c in by_email_raw]
            stripe_info["customers_by_email"] = [
                {"id": c.get("id"), "email": c.get("email"),
                 "created": c.get("created")}
                for c in by_email
            ]
            cust_ids = set()
            if stored_cust_id:
                cust_ids.add(stored_cust_id)
            for c in by_email:
                if c.get("id"):
                    cust_ids.add(c["id"])
            for cid in cust_ids:
                try:
                    subs_raw = stripe.Subscription.list(
                        customer=cid, status="all", limit=10
                    ).data
                    for s_raw in subs_raw:
                        s = _stripe_to_dict(s_raw)
                        stripe_info["subscriptions"].append({
                            "customer_id": cid,
                            "id": s.get("id"),
                            "status": s.get("status"),
                            "cancel_at_period_end": s.get("cancel_at_period_end"),
                            "cancel_at": s.get("cancel_at"),
                            "current_period_end": s.get("current_period_end"),
                            "metadata": s.get("metadata", {}),
                        })
                except Exception as exc:
                    stripe_info.setdefault("subscription_errors", []).append(
                        f"{cid}: {type(exc).__name__}: {exc}"
                    )
        except Exception as exc:
            stripe_info["error"] = f"{type(exc).__name__}: {exc}"

        return {
            "email": email,
            "user_record": user,
            "memberships": memberships,
            "magic_links_count": magic_links_count,
            "stripe": stripe_info,
        }

    @router.get("/kit/status")
    async def kit_status(request: Request):
        await require_admin(request, db)
        import kit
        key = (os.environ.get("KIT_API_KEY") or "").strip()
        return {"enabled": kit.enabled(), "key_prefix": key[:4] if key else "", "looks_v4": key.startswith("kit_"),
                "tags": [kit.TAG_TRIAL, kit.TAG_MONTHLY, kit.TAG_ANNUAL, kit.TAG_CANCELLED]}

    @router.post("/kit/test")
    async def kit_test(request: Request, body: dict):
        """Tag an email with PT Trial right now and report Kit's exact answer."""
        admin_email = await require_admin(request, db)
        import kit
        email = (body.get("email") or admin_email).strip().lower()
        if not kit.enabled():
            raise HTTPException(status_code=400, detail="KIT_API_KEY is empty in this environment")
        try:
            await kit.tag_subscriber_now(email, kit.TAG_TRIAL)
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)[:400])
        return {"ok": True, "email": email, "tag": kit.TAG_TRIAL}

    @router.get("/credits")
    async def credits(request: Request):
        await require_admin(request, db)
        from watchdog import get_credit_status
        return await get_credit_status(db)

    @router.get("/payment-health")
    async def payment_health(request: Request):
        """Show any red flags in the payment pipeline.

        Two failure modes we watch for:
          1. Users linked to a Stripe customer with no active membership row
             (a "stuck" paying customer).
          2. Webhook events with a handler_error stamped on them
             (webhook received, but processing threw an exception).
        """
        await require_admin(request, db)
        now = _now_iso()

        # Stuck users: have stripe_customer_id but no unexpired active
        # membership. These are the people who paid but the app didn't
        # register the sub — same shape as the Stripe SDK v15 bug.
        users_with_customer = await db.users.find(
            {"stripe_customer_id": {"$exists": True, "$ne": None}},
            {"_id": 0, "email": 1, "stripe_customer_id": 1,
             "last_stripe_sync_at": 1, "created_at": 1},
        ).to_list(500)
        stuck = []
        for u in users_with_customer:
            mems = await db.memberships.find(
                {"user_email": u["email"]}, {"_id": 0}
            ).to_list(20)
            has_active = any(
                m.get("status") == "active" and (
                    not m.get("subscription_end_at")
                    or m.get("subscription_end_at") > now
                )
                for m in mems
            )
            if not has_active:
                stuck.append({
                    **u,
                    "memberships_count": len(mems),
                })

        # Webhook events with a handler error stamped.
        failed_webhooks = await (
            db.webhook_events.find(
                {"handler_error": {"$exists": True}},
                {"_id": 0, "external_event_id": 1, "event": 1,
                 "received_at": 1, "handler_error": 1, "handler_error_at": 1},
            )
            .sort("handler_error_at", -1)
            .to_list(50)
        )

        return {
            "stuck_users_count": len(stuck),
            "stuck_users": stuck,
            "failed_webhooks_count": len(failed_webhooks),
            "failed_webhooks": failed_webhooks,
        }

    @router.post("/prewarm/start")
    async def prewarm_start(request: Request):
        """Kick off a background prewarm of the caption cache using the
        curated word list (data/prewarm_words.txt). Returns immediately;
        actual work runs in the background over hours (~1s per word,
        skipping words that are already cached).

        Uses YouTube API quota (~100 units per fresh word). The daily
        Google quota is 10,000 units, so ~100 fresh words per day. Words
        already cached are free.
        """
        import asyncio as _asyncio
        from pathlib import Path
        await require_admin(request, db)

        # Import inside the handler so we don't hard-depend on the module at
        # import time (prewarm.py has its own Mongo connection setup).
        from prewarm import prewarm as _prewarm, read_words

        default_path = Path(__file__).parent / "data" / "prewarm_words.txt"
        try:
            words = read_words(default_path)
        except Exception as exc:
            raise HTTPException(500, f"could_not_read_words: {exc}")

        # Fire and forget — we don't await the task so the response is
        # instant. Errors are logged inside prewarm().
        _asyncio.create_task(_prewarm(words, concurrency=2, delay=0.5))

        return {
            "ok": True,
            "words_queued": len(words),
            "note": (
                "Running in background. Already-cached words are skipped "
                "instantly; fresh words are fetched at ~2/second. Progress "
                "is logged; check /admin/events to see cache growing over "
                "time. Uses ~100 YouTube API units per fresh word (daily "
                "budget: 10,000)."
            ),
        }

    @router.get("/prewarm/status")
    async def prewarm_status(request: Request):
        """Show how much of the prewarm word list is currently cached."""
        from pathlib import Path
        await require_admin(request, db)

        try:
            from prewarm import read_words
            words = read_words(
                Path(__file__).parent / "data" / "prewarm_words.txt"
            )
        except Exception:
            words = []

        total = len(words)
        if not total:
            return {"total": 0, "cached": 0, "pending": 0}

        now_epoch = datetime.now(timezone.utc).timestamp()
        keys = [w.lower() for w in words]
        cached = await db.caption_search_cache.count_documents({
            "query": {"$in": keys},
            "expires_at": {"$gt": now_epoch},
        })
        return {
            "total": total,
            "cached": cached,
            "pending": total - cached,
            "percent": round((cached / total) * 100) if total else 0,
        }

    @router.post("/ingest/channels/start")
    async def ingest_channels_start(request: Request):
        """Kick off a background ingestion of transcripts from every
        curated YouTube channel. Walks each channel's uploads playlist,
        fetches transcripts, and stores them in caption_transcript_cache
        with a `full_text` field so word-in-caption search works locally
        (instant, no YouTube API on every query).

        Runs in the background — response is instant. Progress is stamped
        onto a Mongo doc under `ingest_status`.
        """
        import asyncio as _asyncio
        await require_admin(request, db)

        # Guard against overlapping runs; a lock with no progress for
        # 30 min is a crash leftover and may be taken over.
        status = await db.ingest_status.find_one(
            {"job": "channels"}, {"_id": 0}
        )
        if status and status.get("running"):
            stale = True
            try:
                last = status.get("updated_at") or status.get("started_at") or ""
                stale = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() > 30 * 60
            except Exception:
                pass
            if not stale:
                return {"ok": True, "already_running": True, "status": status}

        await db.ingest_status.update_one(
            {"job": "channels"},
            {"$set": {
                "job": "channels",
                "running": True,
                "started_at": _now_iso(),
                "channels_done": 0,
                "channels_total": 0,
                "totals": {"ingested": 0, "skipped": 0, "failed": 0},
                "last_channel": None,
                "error": None,
            }},
            upsert=True,
        )

        async def _run():
            try:
                from server import caption_service
                from caption_search import CURATED_HANDLES
                await caption_service.ensure_local_indexes()
                # Resolve every curated handle to a channel id.
                ch_ids = await caption_service._get_curated_channel_ids()
                # We need handle+label metadata too so results have context.
                await db.ingest_status.update_one(
                    {"job": "channels"},
                    {"$set": {"channels_total": len(ch_ids)}},
                )
                totals = {"ingested": 0, "skipped": 0, "failed": 0}
                for i, cid in enumerate(ch_ids, start=1):
                    r = await caption_service.ingest_channel_videos(
                        cid, per_channel_limit=200
                    )
                    for k in totals:
                        totals[k] = totals.get(k, 0) + int(r.get(k, 0) or 0)
                    await db.ingest_status.update_one(
                        {"job": "channels"},
                        {"$set": {
                            "channels_done": i,
                            "last_channel": cid,
                            "totals": totals,
                            "updated_at": _now_iso(),
                        }},
                    )
            except Exception as exc:
                await db.ingest_status.update_one(
                    {"job": "channels"},
                    {"$set": {"error": str(exc)[:300]}},
                )
            finally:
                await db.ingest_status.update_one(
                    {"job": "channels"},
                    {"$set": {
                        "running": False,
                        "finished_at": _now_iso(),
                        "last_full_finished_at": _now_iso(),
                    }},
                )

        _asyncio.create_task(_run())
        return {"ok": True}

    @router.get("/ingest/status")
    async def ingest_status(request: Request):
        await require_admin(request, db)
        from caption_search import CURATED_HANDLES
        s = await db.ingest_status.find_one(
            {"job": "channels"}, {"_id": 0}
        )
        indexed = await db.caption_transcript_cache.count_documents(
            {"has_transcript": True}
        )
        by_channel = []
        async for d in db.caption_transcript_cache.aggregate([
            {"$match": {"has_transcript": True}},
            {"$group": {"_id": "$channel_meta.channel_title", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 200},
        ]):
            by_channel.append({"channel": d["_id"] or "(unknown)", "videos": d["n"]})
        stale = False
        if s and s.get("running"):
            try:
                last = s.get("updated_at") or s.get("started_at") or ""
                stale = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() > 30 * 60
            except Exception:
                stale = True
        return {
            "job": s,
            "videos_indexed": indexed,
            "curated_channels": len(CURATED_HANDLES),
            "channels_with_videos": len(by_channel),
            "by_channel": by_channel,
            "stale_lock": stale,
            "hidden_videos": await db.hidden_videos.count_documents({}),
        }

    return router
