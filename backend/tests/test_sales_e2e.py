"""E2E-ish tests for guest checkout, POST checkout, plan change and regressions.

Runs against the live preview backend using REACT_APP_BACKEND_URL. Also
exercises _grant_from_session / _sync_subscription / _mark_cancelled directly
against Mongo to verify DB effects without needing the Stripe Checkout UI.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", ".env"))

import stripe  # noqa: E402
import stripe_payments as sp  # noqa: E402

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
ADMIN_EMAIL = "katherine@katherinebeck.com"
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def admin_session(db):
    """Insert magic link directly and verify to get session cookie."""
    token = f"tok_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    _run(db.magic_links.insert_one({
        "token": token,
        "email": ADMIN_EMAIL,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "expires_at_dt": now + timedelta(minutes=15),
        "consumed": False,
    }))
    s = requests.Session()
    r = s.get(f"{API}/auth/verify?token={token}", allow_redirects=False)
    assert r.status_code in (200, 302, 303), f"verify failed: {r.status_code} {r.text}"
    return s


# ---------------- Guest checkout GET ---------------------------------------

class TestGuestCheckoutGet:
    def test_annual_303(self, db):
        r = requests.get(f"{API}/payments/checkout?plan=annual", allow_redirects=False)
        assert r.status_code == 303
        loc = r.headers.get("location", "")
        assert loc.startswith("https://checkout.stripe.com"), loc
        # payment_transactions row inserted with email null and yearly key
        tx = _run(db.payment_transactions.find_one(
            {"lookup_key": "accent_coach_yearly", "email": None},
            sort=[("created_at", -1)],
        ))
        assert tx is not None
        assert tx["status"] == "initiated"

    def test_monthly_303(self):
        r = requests.get(f"{API}/payments/checkout?plan=monthly", allow_redirects=False)
        assert r.status_code == 303
        assert r.headers.get("location", "").startswith("https://checkout.stripe.com")

    def test_weekly_400_unknown_plan(self):
        r = requests.get(f"{API}/payments/checkout?plan=weekly", allow_redirects=False)
        assert r.status_code == 400
        assert "unknown_plan" in r.text


# ---------------- POST /payments/checkout ----------------------------------

class TestPostCheckout:
    def test_guest_post_returns_url(self):
        r = requests.post(f"{API}/payments/checkout", json={
            "lookup_key": "accent_coach_monthly",
            "origin_url": API,
        })
        assert r.status_code == 200, r.text
        url = r.json().get("checkout_url", "")
        assert url.startswith("https://checkout.stripe.com"), url

    def test_admin_post_binds_customer(self, admin_session, db):
        r = admin_session.post(f"{API}/payments/checkout", json={
            "lookup_key": "accent_coach_monthly",
            "origin_url": API,
        })
        assert r.status_code == 200, r.text
        url = r.json()["checkout_url"]
        # Extract session id from URL
        sid = url.rstrip("/").split("/")[-1].split("#")[0].split("?")[0]
        # Actually simpler: query payment_transactions for latest with admin email
        tx = _run(db.payment_transactions.find_one(
            {"email": ADMIN_EMAIL, "lookup_key": "accent_coach_monthly"},
            sort=[("created_at", -1)],
        ))
        assert tx is not None
        session_id = tx["session_id"]
        s = stripe.checkout.Session.retrieve(session_id)
        assert s.customer, "customer must be set for logged-in checkout"
        md = getattr(s, "metadata", None) or {}
        # md is StripeObject; access via attr or dict
        val = md.get("app_user_email") if isinstance(md, dict) else getattr(md, "app_user_email", None)
        assert val == ADMIN_EMAIL


# ---------------- Guest _grant_from_session flow ---------------------------

class TestGuestGrant:
    def test_simulated_completion_creates_user_and_active_membership(self, db):
        email = f"guest-{uuid.uuid4().hex[:8]}@example.com"
        fake_session = {
            "id": f"cs_test_{uuid.uuid4().hex[:12]}",
            "customer": f"cus_test_{uuid.uuid4().hex[:10]}",
            "subscription": f"sub_test_{uuid.uuid4().hex[:10]}",
            "metadata": {"lookup_key": "accent_coach_monthly"},
            "customer_details": {"email": email},
        }
        _run(sp._grant_from_session(db, fake_session))
        user = _run(db.users.find_one({"email": email}))
        mem = _run(db.memberships.find_one({"user_email": email}))
        assert user is not None
        assert user["stripe_customer_id"] == fake_session["customer"]
        assert mem["status"] == "active"
        assert mem["offer_id"] == "stripe:accent_coach_monthly"
        # cleanup
        _run(db.users.delete_one({"email": email}))
        _run(db.memberships.delete_many({"user_email": email}))


# ---------------- Plan change flow -----------------------------------------

class TestPlanChange:
    def test_monthly_to_annual_to_pastdue_to_cancelled(self, db):
        email = f"throw-{uuid.uuid4().hex[:8]}@example.com"
        customer = f"cus_thr_{uuid.uuid4().hex[:8]}"
        sub_id = f"sub_thr_{uuid.uuid4().hex[:8]}"
        # monthly grant
        _run(sp._grant_from_session(db, {
            "id": f"cs_{uuid.uuid4().hex[:8]}",
            "customer": customer,
            "subscription": sub_id,
            "metadata": {"lookup_key": "accent_coach_monthly", "app_user_email": email},
        }))
        # sync to yearly
        _run(sp._sync_subscription(db, {
            "id": sub_id, "customer": customer, "status": "active",
            "metadata": {"lookup_key": "accent_coach_monthly", "app_user_email": email},
            "items": {"data": [{"price": {"lookup_key": "accent_coach_yearly"}}]},
        }))
        rows = _run(db.memberships.find({"user_email": email}).to_list(10))
        active = [r for r in rows if r["status"] == "active"]
        assert len(active) == 1
        assert active[0]["offer_id"] == "stripe:accent_coach_yearly"
        assert any(r["last_event"] == "superseded" for r in rows)

        # past_due stays active
        _run(sp._sync_subscription(db, {
            "id": sub_id, "customer": customer, "status": "past_due",
            "metadata": {"app_user_email": email},
            "items": {"data": [{"price": {"lookup_key": "accent_coach_yearly"}}]},
        }))
        mem = _run(db.memberships.find_one(
            {"user_email": email, "offer_id": "stripe:accent_coach_yearly"}
        ))
        assert mem["status"] == "active"
        assert mem["last_event"] == "sub_past_due"

        # cancelled
        _run(sp._mark_cancelled(db, {"id": sub_id}))
        mem2 = _run(db.memberships.find_one(
            {"user_email": email, "offer_id": "stripe:accent_coach_yearly"}
        ))
        assert mem2["subscription_end_at"] is not None
        assert mem2["last_event"] == "sub_deleted"

        # cleanup
        _run(db.users.delete_one({"email": email}))
        _run(db.memberships.delete_many({"user_email": email}))


# ---------------- Regressions ---------------------------------------------

class TestRegressions:
    def test_me_unauth_returns_stripe_prices(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 200
        data = r.json()
        prices = data.get("stripe_prices") or []
        keys = {p.get("lookup_key") for p in prices}
        assert "accent_coach_monthly" in keys
        assert "accent_coach_yearly" in keys

    def test_portal_requires_login(self):
        r = requests.post(f"{API}/payments/portal", json={"origin_url": API})
        assert r.status_code == 401

    def test_webhook_bad_signature_400(self):
        r = requests.post(
            f"{API}/stripe/webhook",
            data='{"id":"evt_1","type":"x","data":{"object":{}}}',
            headers={"Content-Type": "application/json", "stripe-signature": "bad"},
        )
        assert r.status_code == 400
