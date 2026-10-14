"""Owner notifications: a short email to the coach when someone starts a
trial, joins, or cancels. Fire-and-forget; never blocks or fails a request.
Every send is logged to `owner_notifications`; an optional `key` makes a
notification one-shot (e.g. one "New member" per Stripe subscription, no
matter which webhook or sync path fires first)."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Iterable, Optional

import resend

from auth import FROM_HEADER

logger = logging.getLogger(__name__)

NOTIFY_EMAIL = os.environ.get("ADMIN_NOTIFY_EMAIL", "info@katherinebeck.com")
_db = None


def set_db(db) -> None:
    global _db
    _db = db


def _html(title: str, lines: Iterable[str]) -> str:
    rows = "".join(
        f'<p style="margin:0 0 8px;font:15px Georgia,serif;color:#111">{line}</p>'
        for line in lines
    )
    return f"""
<div style="background:#f7f5f0;padding:32px 16px">
  <div style="max-width:520px;margin:0 auto;background:#fff;border:1px solid #e5e1d8;padding:28px 32px">
    <div style="font:11px/1 monospace;letter-spacing:.24em;text-transform:uppercase;color:#b8862b;margin-bottom:12px">Pronounce This</div>
    <h1 style="font:600 22px Georgia,serif;color:#111;margin:0 0 16px">{title}</h1>
    {rows}
  </div>
</div>""".strip()


async def claim(key: str) -> bool:
    """Reserve a one-shot key. True if this caller owns it (first), False if
    it was already claimed. Without a DB we can't dedupe, so allow."""
    if _db is None or not key:
        return True
    now = datetime.now(timezone.utc).isoformat()
    r = await _db.owner_notifications.update_one(
        {"key": key}, {"$setOnInsert": {"key": key, "claimed_at": now, "status": "claimed"}}, upsert=True)
    return r.upserted_id is not None


def notify_owner(subject: str, title: str, lines: Iterable[str], key: Optional[str] = None) -> None:
    """Schedule the email; safe to call from any request handler."""
    lines = list(lines)

    async def _send() -> None:
        now = datetime.now(timezone.utc).isoformat()
        record = {"subject": subject, "title": title, "lines": lines, "to": NOTIFY_EMAIL, "sent_at": now}
        try:
            r = await asyncio.to_thread(resend.Emails.send, {
                "from": FROM_HEADER,
                "to": [NOTIFY_EMAIL],
                "subject": f"[Pronounce This] {subject}",
                "html": _html(title, lines),
            })
            record.update({"status": "sent", "resend_id": (r or {}).get("id") if isinstance(r, dict) else getattr(r, "id", None)})
        except Exception as e:
            logger.warning("owner notification failed (%s): %s", subject, e)
            record.update({"status": "failed", "error": str(e)[:300]})
        if _db is not None:
            try:
                if key:
                    await _db.owner_notifications.update_one({"key": key}, {"$set": record})
                else:
                    await _db.owner_notifications.insert_one(record)
            except Exception as exc:  # noqa: BLE001
                logger.debug("owner_notifications log failed: %s", exc)

    try:
        asyncio.get_running_loop().create_task(_send())
    except RuntimeError:
        logger.warning("owner notification skipped (no event loop): %s", subject)
