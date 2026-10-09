"""Monthly scene-page allowance for members, reset on each member's billing day."""
import calendar
from datetime import datetime, timezone
from typing import Optional

MEMBER_PAGE_CAP = 8            # pages per upload (members)
MONTHLY_PAGE_ALLOWANCE = 25    # pages per billing month (default; per-user override in users.page_allowance)
SUPPORT_EMAIL = "info@katherinebeck.com"


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _clamp_day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, min(day, calendar.monthrange(year, month)[1]), tzinfo=timezone.utc)


def cycle_bounds(anchor: datetime, now: datetime) -> tuple:
    """Current cycle [start, end) using the anchor's day-of-month."""
    start = _clamp_day(now.year, now.month, anchor.day)
    if start > now:
        y, m = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
        start = _clamp_day(y, m, anchor.day)
    y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start, _clamp_day(y, m, anchor.day)


async def _anchor(db, email: str, user: Optional[dict]) -> datetime:
    now = datetime.now(timezone.utc)
    best = None
    async for m in db.memberships.find({"user_email": email, "status": "active"}, {"_id": 0, "created_at": 1, "started_at": 1}):
        d = _parse(m.get("started_at") or m.get("created_at"))
        if d and (best is None or d < best):
            best = d
    return best or _parse((user or {}).get("created_at")) or now


async def usage(db, email: str, user: Optional[dict] = None) -> dict:
    user = user or await db.users.find_one({"email": email}, {"_id": 0, "created_at": 1, "page_allowance": 1})
    now = datetime.now(timezone.utc)
    start, end = cycle_bounds(await _anchor(db, email, user), now)
    agg = await db.page_usage.aggregate([
        {"$match": {"email": email, "at": {"$gte": start.isoformat()}}},
        {"$group": {"_id": None, "pages": {"$sum": "$pages"}}},
    ]).to_list(1)
    used = int(agg[0]["pages"]) if agg else 0
    allowance = int((user or {}).get("page_allowance") or MONTHLY_PAGE_ALLOWANCE)
    return {"used": used, "allowance": allowance, "remaining": max(0, allowance - used),
            "cycle_start": start.isoformat(), "resets_at": end.isoformat()}


async def record(db, email: str, pages: int, scene_id: str) -> None:
    await db.page_usage.insert_one({"email": email, "pages": int(pages), "scene_id": scene_id,
                                    "at": datetime.now(timezone.utc).isoformat()})


def limit_message(u: dict, pages: int) -> str:
    resets = _parse(u["resets_at"])
    when = resets.strftime("%b %-d") if resets else "your next billing date"
    if u["remaining"] <= 0:
        return (f"You've used all {u['allowance']} of your scene pages for this billing month. "
                f"Your allowance resets on {when}. Need more right now? Email {SUPPORT_EMAIL} and we'll top you up.")
    return (f"This PDF is {pages} pages but you have {u['remaining']} of {u['allowance']} scene pages left this billing month "
            f"(resets {when}). Try a shorter scene, or email {SUPPORT_EMAIL} for a top-up.")
