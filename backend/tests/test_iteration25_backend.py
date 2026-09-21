"""Iteration-25 backend acceptance tests.

Covers:
- Magic-link verify supports up to 5 uses within the 15-min TTL; 6th
  returns 400 with detail {code:'invalid_or_used_link', email}
- Bogus token -> 400 detail 'invalid_or_used_link' (string form)
- Disposable email -> 400 detail 'disposable_email'
- /api/auth/me sets pt_device cookie
- Signed-in cookie flows through
"""
import asyncio
import os
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://accent-coach-pro.preview.emergentagent.com",
).rstrip("/")

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"


@pytest.fixture
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


async def _seed_magic_link_token(email: str) -> str:
    """Insert a valid magic-link row directly (bypass Resend) and return the token."""
    from datetime import datetime, timedelta, timezone
    import secrets

    mongo = AsyncIOMotorClient(MONGO_URL)
    db = mongo[DB_NAME]
    # ensure user
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"email": email},
        {"$setOnInsert": {
            "email": email,
            "email_key": email,
            "trial_word_used": 0,
            "trial_scene_used": 0,
            "created_at": now.isoformat(),
            "last_login_at": None,
        }},
        upsert=True,
    )
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=15)
    await db.magic_links.insert_one({
        "token": token,
        "email": email,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "expires_at_dt": expires_at,
        "consumed": False,
    })
    mongo.close()
    return token


class TestDisposableEmail:
    def test_disposable_email_returns_400(self, client):
        email = f"user{uuid.uuid4().hex[:6]}@mailinator.com"
        r = client.post(
            f"{BASE_URL}/api/auth/request-magic-link",
            json={"email": email},
        )
        assert r.status_code == 400, r.text
        assert r.json().get("detail") == "disposable_email"


class TestMagicLinkReuse:
    def test_verify_reusable_up_to_5_times(self, client):
        email = f"TEST_reuse_{uuid.uuid4().hex[:8]}@example.com"
        token = asyncio.get_event_loop().run_until_complete(
            _seed_magic_link_token(email)
        )
        # 5 successful verifies
        for i in range(5):
            r = client.get(f"{BASE_URL}/api/auth/verify?token={token}")
            assert r.status_code == 200, f"attempt {i+1}: {r.status_code} {r.text}"
            body = r.json()
            assert body.get("ok") is True
            assert body.get("email") == email
        # 6th must fail
        r6 = client.get(f"{BASE_URL}/api/auth/verify?token={token}")
        assert r6.status_code == 400
        detail = r6.json().get("detail")
        assert isinstance(detail, dict), f"Expected dict, got {detail!r}"
        assert detail.get("code") == "invalid_or_used_link"
        assert detail.get("email") == email

    def test_bogus_token_returns_400_string_detail(self, client):
        r = client.get(f"{BASE_URL}/api/auth/verify?token=bogus_{uuid.uuid4().hex}")
        assert r.status_code == 400
        # No row match -> string detail (per code path in auth.py)
        assert r.json().get("detail") == "invalid_or_used_link"


class TestAuthMe:
    def test_me_unauth_sets_pt_device_cookie(self, client):
        s = requests.Session()  # fresh
        r = s.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        assert r.json().get("authenticated") is False
        assert "pt_device" in s.cookies, f"pt_device cookie not set: {s.cookies}"

    def test_signed_in_me_returns_email(self, client):
        email = f"TEST_signin_{uuid.uuid4().hex[:8]}@example.com"
        token = asyncio.get_event_loop().run_until_complete(
            _seed_magic_link_token(email)
        )
        s = requests.Session()
        r = s.get(f"{BASE_URL}/api/auth/verify?token={token}")
        assert r.status_code == 200
        # Session cookie should be set
        assert "accent_session" in s.cookies
        me = s.get(f"{BASE_URL}/api/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body.get("authenticated") is True
        assert body.get("email") == email
