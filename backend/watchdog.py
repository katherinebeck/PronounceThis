"""ElevenLabs credit watchdog: weekly summary + one-time 80% alert per cycle."""
import asyncio
import logging
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from notify import notify_owner

logger = logging.getLogger(__name__)

ALERT_PCT = 80
CHECK_EVERY_S = 6 * 3600
STATE_KEY = "elevenlabs_watchdog"


def _fetch_subscription() -> dict:
    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=30)
    s = client.user.subscription.get()
    return {
        "tier": s.tier,
        "status": s.status,
        "used": int(s.character_count or 0),
        "limit": int(s.character_limit or 0),
        "resets_at": datetime.fromtimestamp(s.next_character_count_reset_unix, tz=timezone.utc).isoformat()
        if s.next_character_count_reset_unix else None,
    }


async def get_credit_status(db: AsyncIOMotorDatabase) -> dict:
    """Live ElevenLabs usage, or a clear reason why it can't be read."""
    try:
        sub = await asyncio.to_thread(_fetch_subscription)
    except Exception as e:
        msg = str(e)
        reason = ("API key is missing the 'User → Read' permission. Edit the key in ElevenLabs → "
                  "API Keys and enable it." if "user_read" in msg or "missing_permissions" in msg
                  else msg[:200])
        return {"ok": False, "error": reason, "checked_at": datetime.now(timezone.utc).isoformat()}
    pct = round(100 * sub["used"] / sub["limit"], 1) if sub["limit"] else 0
    sub.update({"ok": True, "pct": pct, "remaining": max(0, sub["limit"] - sub["used"]),
                "checked_at": datetime.now(timezone.utc).isoformat()})
    return sub


def _lines(status: dict) -> list[str]:
    return [
        f"Plan: <b>{status['tier']}</b> ({status['status']})",
        f"Used: <b>{status['used']:,}</b> of {status['limit']:,} credits (<b>{status['pct']}%</b>)",
        f"Remaining: {status['remaining']:,} credits ≈ {status['remaining'] // 2500:,} reader-track scenes",
        f"Credits reset: {(status.get('resets_at') or '')[:10]}",
    ]


async def run_check(db: AsyncIOMotorDatabase) -> None:
    status = await get_credit_status(db)
    state = await db.system_state.find_one({"key": STATE_KEY}) or {}
    now = datetime.now(timezone.utc)
    updates = {"last_status": status, "last_checked_at": now.isoformat()}

    if not status["ok"]:
        if not state.get("error_notified"):
            notify_owner("ElevenLabs watchdog can't read credits", "Credit watchdog needs one permission",
                         [status["error"]])
            updates["error_notified"] = True
    else:
        cycle = status.get("resets_at") or "none"
        if status["pct"] >= ALERT_PCT and state.get("alerted_cycle") != cycle:
            notify_owner(f"ElevenLabs at {status['pct']}% — consider upgrading",
                         "ElevenLabs credits running low", _lines(status) +
                         ["Members will see 'audio server is busy' once credits run out. "
                          "Upgrade the plan or enable usage-based billing in ElevenLabs."])
            updates["alerted_cycle"] = cycle
        last_weekly = state.get("last_weekly_at")
        if now.weekday() == 0 and (not last_weekly or last_weekly[:10] != now.isoformat()[:10]):
            notify_owner("Weekly ElevenLabs credit report", "This week's ElevenLabs usage", _lines(status))
            updates["last_weekly_at"] = now.isoformat()

    await db.system_state.update_one({"key": STATE_KEY}, {"$set": updates}, upsert=True)


async def watchdog_loop(db: AsyncIOMotorDatabase) -> None:
    while True:
        try:
            await run_check(db)
        except Exception as e:
            logger.warning("elevenlabs watchdog failed: %s", e)
        await asyncio.sleep(CHECK_EVERY_S)
