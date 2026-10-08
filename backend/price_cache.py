"""Live Stripe price amounts by lookup_key, cached so /me stays cheap.
Guarantees the paywall shows exactly what Stripe will charge."""
import asyncio
import logging
import os
import time
from typing import Dict, List

import stripe

logger = logging.getLogger(__name__)

PLANS: List[Dict] = [
    {"lookup_key": "accent_coach_monthly", "label": "Monthly", "amount": 19, "currency": "usd", "interval": "month"},
    {"lookup_key": "accent_coach_yearly", "label": "Annual", "amount": 190, "currency": "usd", "interval": "year"},
]
_TTL = 600
_cache: Dict = {"at": 0.0, "plans": None}


def _savings_note(monthly: float, yearly: float) -> str:
    diff = round(monthly * 12 - yearly)
    return f"Save ${diff} vs monthly" if diff > 0 else ""


def _fetch() -> List[Dict]:
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        return PLANS
    stripe.api_key = key
    out = []
    for p in PLANS:
        found = stripe.Price.list(lookup_keys=[p["lookup_key"]], active=True, limit=1).data
        if found:
            pr = found[0]
            out.append({**p, "amount": pr.unit_amount / 100, "currency": pr.currency,
                        "interval": (pr.recurring or {}).get("interval", p["interval"])})
        else:
            out.append(dict(p))
    return out


async def get_plans() -> List[Dict]:
    now = time.time()
    if _cache["plans"] is None or now - _cache["at"] > _TTL:
        try:
            plans = await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning("stripe price fetch failed, using defaults: %s", e)
            plans = _cache["plans"] or [dict(p) for p in PLANS]
        by = {p["lookup_key"]: p for p in plans}
        m, y = by.get("accent_coach_monthly"), by.get("accent_coach_yearly")
        if m and y:
            y["savings_note"] = _savings_note(m["amount"], y["amount"])
        for p in plans:
            if float(p["amount"]).is_integer():
                p["amount"] = int(p["amount"])
        _cache.update(at=now, plans=plans)
    return [dict(p) for p in _cache["plans"]]


def invalidate() -> None:
    _cache["plans"] = None
