"""Owner notifications: a short email to the coach when someone starts a
trial, joins, or cancels. Fire-and-forget; never blocks or fails a request."""
import asyncio
import logging
import os
from typing import Iterable

import resend

from auth import FROM_HEADER

logger = logging.getLogger(__name__)

NOTIFY_EMAIL = os.environ.get("ADMIN_NOTIFY_EMAIL", "info@katherinebeck.com")


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


def notify_owner(subject: str, title: str, lines: Iterable[str]) -> None:
    """Schedule the email; safe to call from any request handler."""
    lines = list(lines)

    async def _send() -> None:
        try:
            await asyncio.to_thread(resend.Emails.send, {
                "from": FROM_HEADER,
                "to": [NOTIFY_EMAIL],
                "subject": f"[Pronounce This] {subject}",
                "html": _html(title, lines),
            })
        except Exception as e:
            logger.warning("owner notification failed (%s): %s", subject, e)

    try:
        asyncio.get_running_loop().create_task(_send())
    except RuntimeError:
        logger.warning("owner notification skipped (no event loop): %s", subject)
