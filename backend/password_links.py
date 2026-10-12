"""Set-password links for members: welcome email on join, self-serve
"Forgot password" via our own mailer (Resend) with real delivery status,
and admin copy/send. The Supabase identity is created on the fly."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import resend
from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorDatabase

import supabase_auth
from auth import APP_PUBLIC_URL, FROM_HEADER

logger = logging.getLogger(__name__)

RESET_PATH = "/auth/reset"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def base_url(request: Optional[Request]) -> str:
    origin = request.headers.get("origin") or request.headers.get("referer") if request else None
    if origin:
        u = urlparse(origin)
        return f"{u.scheme}://{u.netloc}"
    return APP_PUBLIC_URL


def _wrap(paragraphs: list[str]) -> str:
    body = "".join(f'<p style="margin:0 0 14px;font:16px/1.55 Georgia,serif;color:#111">{p}</p>' for p in paragraphs)
    return f'<div style="max-width:520px;margin:0 auto;padding:24px 16px">{body}</div>'


def _email(kind: str, link: Optional[str], first_name: str = "", app_url: str = APP_PUBLIC_URL) -> tuple[str, str]:
    """(subject, html) for kind in welcome | reset | nudge | no_account."""
    app_url = app_url.rstrip("/")
    hi = f"Hi {first_name}," if first_name else "Hi there,"
    tip = ('<span style="color:#555;font-size:14px">Using Gmail and can\'t see this? It may be under the '
           '<b>Promotions</b> or <b>Updates</b> tab — search for “Pronounce This”.</span>')
    if kind == "welcome":
        return ("Your Pronounce This access — set your password", _wrap([
            hi,
            "Welcome to <b>Pronounce This</b>. You just need to choose a password once, and you're in.",
            f'<b>Step 1.</b> If you haven\'t set up your password yet, click this button and choose a password:<br><br><a href="{link}" style="display:inline-block;background:#d9a441;color:#111;text-decoration:none;font-weight:bold;padding:12px 22px;border:1px solid #111">Set my password →</a>',
            f'<b>Step 2.</b> That\'s it — you\'ll land straight in the app. Next time, go to <a href="{app_url}/login" style="color:#b8862b">{app_url.replace("https://", "")}/login</a> and enter your email address with the password you chose. If this is a Gmail address you can also just tap <b>Continue with Google</b>.',
            f"This button works for 4 hours. If it has expired by the time you open this, no problem: go to <a href=\"{app_url}/login\" style=\"color:#b8862b\">{app_url.replace('https://', '')}/login</a>, tap <b>Forgot password?</b> and a fresh link will arrive within a minute.",
            "See you in there,<br>The Pronounce This Team",
            tip,
        ]))
    if kind == "member":
        return ("You're in — welcome to Pronounce This", _wrap([
            hi,
            "Thank you for joining <b>Pronounce This</b>. Your membership is active and everything is unlocked.",
            f'<a href="{app_url}/app" style="display:inline-block;background:#ef5973;color:#fff;text-decoration:none;font-weight:bold;padding:12px 22px;border-radius:999px">Open Pronounce This →</a>',
            "<b>What you have:</b><br>"
            "• <b>Pronounce This Word</b> — type any word, name or place to see it written phonetically (IPA), hear it in a Standard American accent, and watch real Americans say it.<br>"
            "• <b>Pronounce This Scene</b> — upload your sides (text-based PDF, up to 8 pages), pick your character, hear every line, and practice with sound lists from your scene.<br>"
            "• <b>Downloads</b> — your character's lines to practice with, and your reader's lines to run lines or film your self-tape.<br>"
            "• <b>25 scene pages every month</b>, resetting on your billing date. Need more for a big audition? Just reply to this email.",
            f'Log in any time at <a href="{app_url}/login" style="color:#ef5973">{app_url.replace("https://", "")}/login</a> with this email address (or Continue with Google). Manage or cancel your plan from the account menu.',
            "Break a leg,<br>The Pronounce This Team",
            tip,
        ]))
    if kind == "nudge":
        return ("Your Pronounce This access is waiting", _wrap([
            hi,
            "Just a gentle nudge — your Pronounce This access is all set up and waiting, but you haven't logged in yet. Choosing a password takes ten seconds:",
            f'<a href="{link}" style="display:inline-block;background:#d9a441;color:#111;text-decoration:none;font-weight:bold;padding:12px 22px;border:1px solid #111">Set my password →</a>',
            f'Then log in any time at <a href="{app_url}/login" style="color:#b8862b">{app_url.replace("https://", "")}/login</a> with this email and that password (or Continue with Google). The button works for 4 hours — after that, tap <b>Forgot password?</b> on the login page for a fresh one. If anything\'s unclear, just reply to this email.',
            "The Pronounce This Team",
            tip,
        ]))
    if kind == "reset":
        return ("Pronounce This — your password link", _wrap([
            hi,
            "Here's your link to choose a new Pronounce This password:",
            f'<a href="{link}" style="color:#b8862b;font-weight:bold">Choose a new password →</a>',
            "If you didn't ask for this, you can ignore this email — nothing changes.",
            "The Pronounce This Team",
            tip,
        ]))
    return ("Pronounce This — no account under this email", _wrap([
        "Hi there,",
        "Someone (probably you) asked for a Pronounce This password link for this address, but there's no account under it yet.",
        "If you joined through group coaching, try the email you used when you joined. "
        "Otherwise you can start free at <a href=\"" + APP_PUBLIC_URL + "\" style=\"color:#b8862b\">Pronounce This</a>.",
        "The Pronounce This Team",
    ]))


async def _send(to: str, subject: str, html: str) -> Optional[str]:
    r = await asyncio.to_thread(resend.Emails.send, {"from": FROM_HEADER, "to": [to], "subject": subject, "html": html})
    return (r or {}).get("id") if isinstance(r, dict) else getattr(r, "id", None)


async def make_link(email: str, base: str) -> Optional[str]:
    if not await supabase_auth.ensure_identity(email):
        return None
    return await supabase_auth.generate_set_password_link(email, f"{base}{RESET_PATH}")


async def send_link_email(db: AsyncIOMotorDatabase, email: str, kind: str, base: str) -> dict:
    """Email a set/reset-password link (or a 'no account' note). Records the
    send in `auth_emails` so the UI can show real delivery status."""
    email = email.strip().lower()
    account = await db.users.find_one({"email": email}, {"_id": 1, "first_name": 1})
    link = None
    if account:
        link = await make_link(email, base)
        if not link:
            logger.warning("password link unavailable for %s (service key / Supabase)", email)
            return {"ok": False, "status": "unavailable"}
    else:
        kind = "no_account"
    subject, html = _email(kind, link, (account or {}).get("first_name") or "", base)
    try:
        rid = await _send(email, subject, html)
    except Exception as exc:  # noqa: BLE001
        logger.warning("password link email to %s failed: %s", email, exc)
        return {"ok": False, "status": "failed"}
    doc = {"email": email, "kind": kind, "resend_id": rid, "status": "sent", "sent_at": _now_iso()}
    await db.auth_emails.insert_one(dict(doc))
    if kind in ("welcome", "nudge"):
        await db.users.update_one({"email": email}, {"$set": {f"{kind}_sent_at": doc["sent_at"]}})
    doc.pop("_id", None)
    return {"ok": True, **doc}


async def delivery_status(db: AsyncIOMotorDatabase, email: str) -> dict:
    """Latest send for this email, refreshed from Resend (sent → delivered / bounced)."""
    email = email.strip().lower()
    doc = await db.auth_emails.find_one({"email": email}, {"_id": 0}, sort=[("sent_at", -1)])
    if not doc:
        return {"status": "none"}
    if doc.get("resend_id") and doc.get("status") not in ("delivered", "bounced", "complained"):
        try:
            r = await asyncio.to_thread(resend.Emails.get, doc["resend_id"])
            ev = (r or {}).get("last_event") if isinstance(r, dict) else getattr(r, "last_event", None)
            if ev and ev != doc.get("status"):
                doc["status"] = ev
                await db.auth_emails.update_one({"resend_id": doc["resend_id"]}, {"$set": {"status": ev}})
        except Exception as exc:  # noqa: BLE001
            logger.debug("resend status lookup failed: %s", exc)
    return {"status": doc.get("status"), "sent_at": doc.get("sent_at"), "kind": doc.get("kind"), "to": email}


def welcome_if_new(db: AsyncIOMotorDatabase, email: str, base: Optional[str] = None) -> None:
    """Fire-and-forget: a member who has never signed in gets the welcome
    set-password email (Kajabi webhook / admin grant)."""
    async def _go():
        try:
            u = await db.users.find_one({"email": email}, {"last_login_at": 1, "supabase_sub": 1})
            if u and u.get("last_login_at") is None:
                await send_link_email(db, email, "welcome", base or APP_PUBLIC_URL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("welcome email for %s failed: %s", email, exc)
    try:
        asyncio.get_running_loop().create_task(_go())
    except RuntimeError:
        pass


async def send_member_welcome(db: AsyncIOMotorDatabase, email: str) -> Optional[str]:
    """Once per member, right after a Stripe purchase: never-signed-in buyers
    get the set-password welcome; existing users get the 'you're in' note.
    Returns the kind sent, or None if already sent / failed."""
    email = email.strip().lower()
    claimed = await db.users.find_one_and_update(
        {"email": email, "member_welcome_sent_at": None},
        {"$set": {"member_welcome_sent_at": _now_iso()}},
        projection={"last_login_at": 1, "first_name": 1})
    if not claimed:
        return None
    try:
        if claimed.get("last_login_at") is None:
            res = await send_link_email(db, email, "welcome", APP_PUBLIC_URL)
            ok, kind = res.get("ok", False), "welcome"
        else:
            subject, html = _email("member", None, claimed.get("first_name") or "")
            rid = await _send(email, subject, html)
            await db.auth_emails.insert_one({"email": email, "kind": "member", "resend_id": rid, "status": "sent", "sent_at": _now_iso()})
            ok, kind = True, "member"
    except Exception as exc:  # noqa: BLE001
        logger.warning("member welcome email to %s failed: %s", email, exc)
        ok, kind = False, None
    if not ok:
        await db.users.update_one({"email": email}, {"$unset": {"member_welcome_sent_at": ""}})
    return kind


NUDGE_AFTER_HOURS = 24


async def run_onboarding_nudges(db: AsyncIOMotorDatabase, limit: int = 50) -> dict:
    """Runs every few hours: members who got a welcome email ≥24h ago, never
    signed in and haven't been nudged get one gentle reminder with a fresh link."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=NUDGE_AFTER_HOURS)).isoformat()
    cursor = db.users.find(
        {"welcome_sent_at": {"$lte": cutoff}, "last_login_at": None,
         "nudge_sent_at": {"$exists": False}, "trial_blocked": {"$ne": True}},
        {"_id": 0, "email": 1},
    ).limit(limit)
    sent = failed = 0
    async for u in cursor:
        res = await send_link_email(db, u["email"], "nudge", APP_PUBLIC_URL)
        if res.get("ok"):
            sent += 1
        else:
            failed += 1
            await db.users.update_one({"email": u["email"]}, {"$set": {"nudge_sent_at": None}})
        await asyncio.sleep(0.3)
    logger.info("onboarding nudges: sent %d, failed %d", sent, failed)
    return {"sent": sent, "failed": failed}
