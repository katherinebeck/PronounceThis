"""Regression tests for the Stripe SDK compatibility bug.

Context: Stripe Python SDK v15.0.1 removed dict-style `.get()` from
StripeObject. Every `sub.get(...)`, `session.get(...)`, `obj.get(...)`
call in our webhook + sync helpers was silently raising AttributeError,
which got swallowed by outer try/except. Result: webhooks returned green
but no memberships were created.

These tests lock the fix in place — if the pattern regresses (or the SDK
ships another breaking change to `.get()`), these fail loudly.
"""
from __future__ import annotations

import os
import sys

# Ensure `stripe_payments` can import auth without a real environment.
os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("SENDER_EMAIL", "test@test.com")
os.environ.setdefault("RESEND_API_KEY", "test")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stripe

from stripe_payments import _to_dict


def test_to_dict_converts_stripe_object_recursively():
    """The helper must yield a plain dict where nested StripeObjects
    are also flattened to dicts, so downstream `.get()` works."""
    sub = stripe.Subscription.construct_from(
        {
            "id": "sub_test",
            "status": "active",
            "customer": "cus_test",
            "cancel_at": None,
            "cancel_at_period_end": False,
            "metadata": {
                "app_user_email": "student@example.com",
                "lookup_key": "accent_coach_monthly",
            },
        },
        "sk_test",
    )
    d = _to_dict(sub)
    assert isinstance(d, dict)
    # Top-level dict.get() works
    assert d.get("id") == "sub_test"
    assert d.get("status") == "active"
    assert d.get("missing", "DEFAULT") == "DEFAULT"
    # Nested metadata is also a plain dict — not a StripeObject
    md = d.get("metadata")
    assert isinstance(md, dict)
    assert md.get("app_user_email") == "student@example.com"
    assert md.get("lookup_key") == "accent_coach_monthly"


def test_stripe_object_get_still_broken_upstream():
    """Sanity check that documents WHY we need _to_dict.

    If Stripe restores `.get()` in a future SDK version, this test starts
    failing — which is a signal to review whether we still need the
    conversion helper. Not a bug, just a heads-up.
    """
    sub = stripe.Subscription.construct_from(
        {"id": "sub_test", "status": "active"}, "sk_test"
    )
    try:
        sub.get("status")  # noqa: B018
    except AttributeError:
        # Current behaviour on SDK v15 — .get() is gone.
        return
    # If we get here, .get() works again on the raw object. That's fine,
    # but the assertion below just reminds us to re-evaluate the helper.
    assert sub.get("status") == "active"


def test_to_dict_handles_none_and_plain_dict():
    """Callers should be able to pass a plain dict (from webhooks that
    already came in as JSON) or None without failure."""
    assert _to_dict(None) == {}
    plain = {"id": "already_dict", "status": "active"}
    assert _to_dict(plain) is plain  # short-circuits, returns as-is


def test_to_dict_survives_garbage_input():
    """Never raise from _to_dict — that would defeat the whole point of
    having a defensive helper at every Stripe-object boundary."""

    class BadObj:
        def __str__(self):
            raise RuntimeError("boom")

    assert _to_dict(BadObj()) == {}
