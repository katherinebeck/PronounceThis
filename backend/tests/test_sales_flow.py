"""Guest checkout + plan-change membership logic (no Stripe network calls)."""
import asyncio, os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import stripe_payments as sp


@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    name = f"test_sales_{uuid.uuid4().hex[:8]}"
    yield client[name]
    asyncio.get_event_loop().run_until_complete(client.drop_database(name))


def test_session_email_prefers_metadata_then_customer_details():
    assert sp._session_email({"metadata": {"app_user_email": "A@x.com"}}) == "a@x.com"
    assert sp._session_email({"customer_details": {"email": "Guest@X.com"}}) == "guest@x.com"
    assert sp._session_email({}) == ""


def test_sub_lookup_key_from_price_beats_metadata():
    sub = {"metadata": {"lookup_key": "accent_coach_monthly"},
           "items": {"data": [{"price": {"lookup_key": "accent_coach_yearly"}}]}}
    assert sp._sub_lookup_key(sub) == "accent_coach_yearly"
    assert sp._sub_lookup_key({"metadata": {"lookup_key": "accent_coach_monthly"}}) == "accent_coach_monthly"


def test_guest_checkout_grant_creates_user_and_membership(db):
    async def run():
        session = {"id": "cs_1", "customer": "cus_1", "subscription": "sub_1",
                   "metadata": {"lookup_key": "accent_coach_monthly"},
                   "customer_details": {"email": "New@Buyer.com"}}
        await sp._grant_from_session(db, session)
        user = await db.users.find_one({"email": "new@buyer.com"})
        mem = await db.memberships.find_one({"user_email": "new@buyer.com"})
        assert user and user["stripe_customer_id"] == "cus_1"
        assert mem["status"] == "active" and mem["offer_id"] == "stripe:accent_coach_monthly"
    asyncio.get_event_loop().run_until_complete(run())


def test_monthly_to_annual_switch_supersedes_and_relabels(db):
    async def run():
        await db.users.insert_one({"email": "u@x.com", "stripe_customer_id": "cus_9"})
        await sp._grant_from_session(db, {"id": "cs", "customer": "cus_9", "subscription": "sub_9",
                                          "metadata": {"lookup_key": "accent_coach_monthly", "app_user_email": "u@x.com"}})
        # Portal switched the price; metadata still says monthly.
        await sp._sync_subscription(db, {"id": "sub_9", "customer": "cus_9", "status": "active",
                                         "metadata": {"lookup_key": "accent_coach_monthly", "app_user_email": "u@x.com"},
                                         "items": {"data": [{"price": {"lookup_key": "accent_coach_yearly"}}]}})
        rows = await db.memberships.find({"user_email": "u@x.com"}).to_list(10)
        active = [r for r in rows if r["status"] == "active"]
        assert len(active) == 1 and active[0]["offer_id"] == "stripe:accent_coach_yearly"
        assert active[0]["offer_title"].endswith("Annual")
        assert any(r["last_event"] == "superseded" for r in rows)
    asyncio.get_event_loop().run_until_complete(run())


def test_past_due_keeps_access_in_sync(db):
    async def run():
        await db.users.insert_one({"email": "p@x.com", "stripe_customer_id": "cus_p"})
        await sp._sync_subscription(db, {"id": "sub_p", "customer": "cus_p", "status": "past_due",
                                         "items": {"data": [{"price": {"lookup_key": "accent_coach_monthly"}}]}})
        mem = await db.memberships.find_one({"user_email": "p@x.com"})
        assert mem["status"] == "active"
    asyncio.get_event_loop().run_until_complete(run())
