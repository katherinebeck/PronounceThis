"""Backend tests for the word-playback + verify flow (review iteration 24).

Covers:
- /api/pronounce for 'server' (single IPA) and 'produce' (2 variants)
- /api/tts for word + arpabet variants (success + invalid_arpabet 400)
- /api/auth/verify grace window on used token and rejection on bogus token
"""
import os
import time
import asyncio
import requests
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _auth_session():
    """Create magic link for admin, verify it, return a Session with cookie."""
    email = "katherine@katherinebeck.com"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/request-magic-link", json={"email": email}, timeout=15)
    assert r.status_code in (200, 202), r.text

    async def _fetch():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        doc = await db.magic_links.find_one({"email": email, "consumed": False}, sort=[("created_at", -1)])
        client.close()
        return doc

    doc = asyncio.run(_fetch())
    assert doc, "no magic link created"
    v = s.get(f"{API}/auth/verify", params={"token": doc["token"]}, timeout=15, allow_redirects=False)
    assert v.status_code == 200, v.text
    return s


@pytest.fixture(scope="module")
def auth_http():
    return _auth_session()


# ---------- /api/pronounce ----------
def test_pronounce_server_ipa(http):
    r = http.get(f"{API}/pronounce", params={"word": "server"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("word", "").lower() == "server"
    # Expected exact IPA (with syllable break + r-colored vowels)
    assert data.get("ipa") == "ˈsɝ·vɚ", f"unexpected IPA: {data.get('ipa')}"


def test_pronounce_produce_heteronym(http):
    r = http.get(f"{API}/pronounce", params={"word": "produce"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    variants = data.get("variants") or []
    assert len(variants) == 2, f"expected 2 variants, got {len(variants)}: {variants}"
    labels = {(v.get("label") or "").lower() for v in variants}
    assert {"noun", "verb"}.issubset(labels), f"labels: {labels}"
    # Each variant should carry an arpabet string used by the FE Hear button.
    for v in variants:
        assert v.get("arpabet"), f"variant missing arpabet: {v}"


# ---------- /api/tts ----------
def test_tts_produce_verb_arpabet(auth_http):
    payload = {"word": "produce", "arpabet": "P R OW1 D UW0 S"}
    r = auth_http.post(f"{API}/tts", json=payload, timeout=45)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("audio_b64"), "missing audio_b64"
    assert len(data["audio_b64"]) > 500, "audio_b64 seems empty/tiny"


def test_tts_invalid_arpabet_returns_400(auth_http):
    payload = {"word": "produce", "arpabet": "XX YY"}
    r = auth_http.post(f"{API}/tts", json=payload, timeout=30)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "invalid_arpabet" in str(detail).lower(), f"unexpected detail: {detail}"


# ---------- /api/auth/verify ----------
def _insert_magic_link(email):
    """Insert a fresh magic link via the public endpoint and return the token from DB."""
    async def _run():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        # request via API so we exercise real path
        r = requests.post(f"{API}/auth/request-magic-link", json={"email": email}, timeout=15)
        assert r.status_code in (200, 202), r.text
        doc = await db.magic_links.find_one(
            {"email": email, "consumed": False}, sort=[("created_at", -1)]
        )
        client.close()
        return doc

    return asyncio.get_event_loop().run_until_complete(_run()) if False else asyncio.run(_run())


def test_verify_grace_window_and_bogus():
    # Bogus token — should be 400 invalid_or_used_link
    r = requests.get(f"{API}/auth/verify", params={"token": "definitely-not-a-real-token-xyz"}, timeout=15, allow_redirects=False)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert detail in ("invalid_or_used_link", "invalid_link"), f"got {detail}"

    # Grace window: verify a valid token twice within 120s; both should be 200.
    email = "katherine@katherinebeck.com"
    doc = _insert_magic_link(email)
    assert doc and doc.get("token"), "could not create magic link"
    token = doc["token"]

    r1 = requests.get(f"{API}/auth/verify", params={"token": token}, timeout=15, allow_redirects=False)
    assert r1.status_code == 200, r1.text
    # Second call within grace window (well under 120s)
    time.sleep(2)
    r2 = requests.get(f"{API}/auth/verify", params={"token": token}, timeout=15, allow_redirects=False)
    assert r2.status_code == 200, f"grace window failed: {r2.status_code} {r2.text}"
