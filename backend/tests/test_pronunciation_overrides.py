"""Tests for admin pronunciation-override endpoints + /api/tts manual_override flag.

Covers iteration 19 review request: admin uploads manual MP3 override, listed,
served on /api/tts with manual_override=true, deletable; unauthenticated 401;
empty file 400; oversize 413; TTS unchanged when no override.
"""
import base64
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

# --- Env / constants -------------------------------------------------------

# Load /app/backend/.env for MONGO_URL + DB_NAME + ADMIN_EMAILS
_env_path = Path("/app/backend/.env")
for line in _env_path.read_text().splitlines():
    if "=" not in line or line.strip().startswith("#"):
        continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip().strip('"'))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://accent-coach-pro.preview.emergentagent.com"
MONGO_URL = os.environ["MONGO_URL"].strip('"')
DB_NAME = os.environ["DB_NAME"].strip('"')
ADMIN_EMAIL = os.environ.get("ADMIN_EMAILS", "katherine@katherinebeck.com").split(",")[0].strip().lower()

TEST_WORD = "test_word_la_override"
NEVER_OVERRIDE_WORD = "testword_xyz_never"


# The endpoint doesn't parse MP3 structure — just enforces size + content-type.
# Use a tiny opaque payload with the MP3 magic bytes ("ID3" or 0xFFFB frame sync).
TINY_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 128  # ~522 bytes


# --- Fixtures --------------------------------------------------------------

@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="module")
def admin_session(mongo):
    """Insert a magic-link token directly, GET /api/auth/verify, capture cookie."""
    # Ensure the admin user row exists (verify writes last_login_at).
    mongo.users.update_one(
        {"email": ADMIN_EMAIL},
        {"$setOnInsert": {
            "email": ADMIN_EMAIL,
            "trial_word_used": 0,
            "trial_scene_used": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login_at": None,
        }},
        upsert=True,
    )
    # Ensure an active membership so /api/tts is subscriber-gated (no trial exhaustion).
    mongo.memberships.update_one(
        {"user_email": ADMIN_EMAIL, "offer_id": "manual_grant"},
        {"$set": {
            "user_email": ADMIN_EMAIL,
            "offer_id": "manual_grant",
            "offer_title": "TEST_admin_grant",
            "status": "active",
            "subscription_end_at": None,
            "last_event": "test_setup",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    token = secrets.token_urlsafe(24)
    mongo.magic_links.insert_one({
        "token": token,
        "email": ADMIN_EMAIL,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "consumed": False,
    })

    sess = requests.Session()
    r = sess.get(f"{BASE_URL}/api/auth/verify", params={"token": token}, timeout=30)
    assert r.status_code == 200, f"verify failed: {r.status_code} {r.text}"
    assert "accent_session" in sess.cookies, f"no session cookie set. cookies={sess.cookies.items()}"
    yield sess

    # Teardown: clean up test-created overrides.
    mongo.audio_cache.delete_many({"word": {"$regex": "^test_word_"}})
    mongo.audio_cache.delete_many({"word": NEVER_OVERRIDE_WORD})
    mongo.audio_cache.delete_many({"word": "los angeles", "manual_override": True})


# --- Tests: admin gating ---------------------------------------------------

class TestAdminGating:
    def test_upload_unauthenticated_returns_401(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/pronunciation-overrides",
            data={"word": "los angeles"},
            files={"file": ("x.mp3", TINY_MP3, "audio/mpeg")},
            timeout=30,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"

    def test_list_unauthenticated_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/pronunciation-overrides", timeout=30)
        assert r.status_code in (401, 403)


# --- Tests: upload / validation --------------------------------------------

class TestUploadValidation:
    def test_upload_empty_file_returns_400(self, admin_session):
        r = admin_session.post(
            f"{BASE_URL}/api/admin/pronunciation-overrides",
            data={"word": TEST_WORD},
            files={"file": ("empty.mp3", b"", "audio/mpeg")},
            timeout=30,
        )
        assert r.status_code == 400
        assert "empty_file" in r.text

    def test_upload_oversize_returns_413(self, admin_session):
        # Just over 2MB.
        big = b"\x00" * (2 * 1024 * 1024 + 100)
        r = admin_session.post(
            f"{BASE_URL}/api/admin/pronunciation-overrides",
            data={"word": TEST_WORD},
            files={"file": ("big.mp3", big, "audio/mpeg")},
            timeout=60,
        )
        assert r.status_code == 413
        assert "file_too_large_max_2mb" in r.text


# --- Tests: happy path CRUD ------------------------------------------------

class TestOverrideCRUD:
    def test_upload_ok(self, admin_session, mongo):
        r = admin_session.post(
            f"{BASE_URL}/api/admin/pronunciation-overrides",
            data={"word": "Los Angeles"},   # will be lowercased server-side
            files={"file": ("la.mp3", TINY_MP3, "audio/mpeg")},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["word"] == "los angeles"
        assert body["byte_size"] == len(TINY_MP3)
        assert body["content_type"] == "audio/mpeg"

        # Verify DB row.
        doc = mongo.audio_cache.find_one({"word": "los angeles"})
        assert doc is not None
        assert doc["manual_override"] is True
        assert doc["byte_size"] == len(TINY_MP3)
        assert base64.b64decode(doc["audio_b64"]) == TINY_MP3

    def test_list_strips_audio_b64(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/admin/pronunciation-overrides", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["count"], int)
        assert body["count"] >= 1
        words = {o["word"] for o in body["overrides"]}
        assert "los angeles" in words
        for o in body["overrides"]:
            assert "audio_b64" not in o, "list view must strip audio_b64"
            assert "word" in o and "byte_size" in o and "content_type" in o

    def test_tts_uses_override_for_subscriber(self, admin_session, mongo):
        r = admin_session.post(
            f"{BASE_URL}/api/tts",
            json={"word": "Los Angeles"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["manual_override"] is True
        assert body["cached"] is True
        # audio_b64 must match what we uploaded.
        assert base64.b64decode(body["audio_b64"]) == TINY_MP3

    def test_tts_manual_override_false_for_uncached_word(self, admin_session, mongo):
        # Ensure no existing cache row.
        mongo.audio_cache.delete_many({"word": NEVER_OVERRIDE_WORD})
        r = admin_session.post(
            f"{BASE_URL}/api/tts",
            json={"word": NEVER_OVERRIDE_WORD},
            timeout=60,
        )
        # Might 200 (Eleven works) or 502 (Eleven quota) — either way,
        # if it's 200, manual_override must be false.
        if r.status_code == 200:
            body = r.json()
            assert body["manual_override"] is False
        else:
            pytest.skip(f"ElevenLabs returned {r.status_code}: {r.text[:200]}")

    def test_delete_override(self, admin_session, mongo):
        r = admin_session.post(
            f"{BASE_URL}/api/admin/pronunciation-overrides/delete",
            json={"word": "Los Angeles"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["deleted"] == 1

        # Confirm gone from list.
        r2 = admin_session.get(f"{BASE_URL}/api/admin/pronunciation-overrides", timeout=30)
        assert r2.status_code == 200
        words = {o["word"] for o in r2.json()["overrides"]}
        assert "los angeles" not in words

        # Confirm gone in DB.
        assert mongo.audio_cache.find_one({"word": "los angeles", "manual_override": True}) is None


# --- Regression: existing endpoints untouched ------------------------------

class TestRegression:
    def test_auth_me_still_has_stripe_prices(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "stripe_prices" in body, f"AuthMeResponse missing stripe_prices: {list(body.keys())}"

    def test_scenes_endpoint_200(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/scenes", timeout=30)
        assert r.status_code == 200, r.text

    def test_caption_search_endpoint_200(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/caption-search",
                              params={"q": "hello"}, timeout=30)
        assert r.status_code == 200, r.text
