"""Kit (ConvertKit) v4 tagging. Fire-and-forget; a blank KIT_API_KEY disables it."""
import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.kit.com/v4"
TAG_TRIAL = "PT Trial"
TAG_TRIAL_DONE = "PT Trial Done"
TAG_MONTHLY = "PT Monthly"
TAG_ANNUAL = "PT Annual"


def member_tag(lookup_key: str) -> str:
    return TAG_ANNUAL if "year" in (lookup_key or "").lower() or "annual" in (lookup_key or "").lower() else TAG_MONTHLY
TAG_CANCELLED = "PT Cancelled"

_tag_ids: dict[str, int] = {}


def _api_key() -> str:
    return (os.environ.get("KIT_API_KEY") or "").strip()


def enabled() -> bool:
    return bool(_api_key())


async def _request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    for attempt in range(3):
        r = await client.request(method, path, **kwargs)
        if r.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
            break
        await asyncio.sleep(2 ** attempt)
    if r.is_error:
        raise RuntimeError(f"Kit {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


async def _tag_id(client: httpx.AsyncClient, name: str) -> int:
    if name not in _tag_ids:
        data = await _request(client, "POST", "/tags", json={"name": name})
        _tag_ids[name] = int(data["tag"]["id"])
    return _tag_ids[name]


async def tag_subscriber_now(email: str, tag_name: str) -> None:
    headers = {"X-Kit-Api-Key": _api_key(), "Accept": "application/json"}
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=10) as client:
        tag_id = await _tag_id(client, tag_name)
        await _request(client, "POST", "/subscribers",
                       json={"email_address": email, "state": "active"})
        await _request(client, "POST", f"/tags/{tag_id}/subscribers",
                       json={"email_address": email})
    logger.info("kit: tagged %s as %r", email, tag_name)


async def list_tags() -> list:
    """All tags in the connected Kit account (follows cursor pagination)."""
    headers = {"X-Kit-Api-Key": _api_key(), "Accept": "application/json"}
    out, cursor = [], None
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=10) as client:
        for _ in range(20):
            params = {"per_page": 500}
            if cursor:
                params["after"] = cursor
            data = await _request(client, "GET", "/tags", params=params)
            out.extend(data.get("tags") or [])
            pag = data.get("pagination") or {}
            if not pag.get("has_next_page"):
                break
            cursor = pag.get("end_cursor")
    return out


async def account_info() -> dict:
    headers = {"X-Kit-Api-Key": _api_key(), "Accept": "application/json"}
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=10) as client:
        data = await _request(client, "GET", "/account")
    acct = data.get("account") or data
    return {"name": acct.get("name"), "primary_email": acct.get("primary_email_address"), "plan": acct.get("plan_type")}


def tag_subscriber(email: str, tag_name: str) -> None:
    """Schedule the Kit sync; safe to call from any request handler."""
    if not enabled() or not email:
        return

    async def _run() -> None:
        try:
            await tag_subscriber_now(email, tag_name)
        except Exception as e:
            logger.warning("kit sync failed (%s / %s): %s", tag_name, email, e)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        logger.warning("kit sync skipped (no event loop): %s", tag_name)
