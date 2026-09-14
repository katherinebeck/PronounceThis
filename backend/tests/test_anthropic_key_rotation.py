"""Verify Claude integration works with rotated ANTHROPIC_API_KEY.
Backend-only, read-only verification (no .env/db/auth mutation)."""
import os
import re
import time
import asyncio
import pytest
import requests
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import dotenv_values

BACKEND_ENV = dotenv_values("/app/backend/.env")
FRONTEND_ENV = dotenv_values("/app/frontend/.env")
BASE_URL = FRONTEND_ENV["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "katherine@katherinebeck.com"


# --- .env / llm.py sanity ---
def test_env_has_single_anthropic_key_with_expected_prefix():
    raw = Path("/app/backend/.env").read_text().splitlines()
    lines = [l for l in raw if l.startswith("ANTHROPIC_API_KEY")]
    assert len(lines) == 1, f"Expected 1 ANTHROPIC_API_KEY line, got {len(lines)}"
    key = BACKEND_ENV["ANTHROPIC_API_KEY"]
    assert key.startswith("sk-ant-api03-K8ziBQp"), f"Unexpected key prefix: {key[:25]}"


def test_llm_prefers_anthropic_over_emergent():
    src = Path("/app/backend/llm.py").read_text()
    # anthropic branch must appear before emergent branch
    a = src.index("ANTHROPIC_API_KEY")
    e = src.index("EMERGENT_LLM_KEY")
    assert a < e, "llm.py must check ANTHROPIC_API_KEY first"


# --- Anonymous pronounce (no Claude) ---
def test_anonymous_pronounce_returns_none_source():
    r = requests.get(f"{BASE_URL}/api/pronounce", params={"word": "Vrelthanor"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("source") == "none", data
    assert data.get("ipa") in (None, ""), data


# --- Authenticated calls via magic link ---
@pytest.fixture(scope="module")
def session_cookie():
    # Read newest UNCONSUMED token straight from Mongo to avoid rate-limiting.
    # Only request a new magic link if no usable token exists.
    async def _fetch():
        client = AsyncIOMotorClient(BACKEND_ENV["MONGO_URL"])
        db = client[BACKEND_ENV["DB_NAME"]]
        doc = await db.magic_links.find_one(
            {"email": ADMIN_EMAIL, "consumed": False},
            sort=[("created_at", -1)],
        )
        client.close()
        return doc

    doc = asyncio.get_event_loop().run_until_complete(_fetch())
    if not doc:
        # Request a magic link (rate-limited: at most one)
        rr = requests.post(
            f"{BASE_URL}/api/auth/request-magic-link",
            json={"email": ADMIN_EMAIL},
            timeout=15,
        )
        assert rr.status_code in (200, 202), rr.text
        time.sleep(1.0)
        doc = asyncio.get_event_loop().run_until_complete(_fetch())
        assert doc, "No magic link token found in Mongo after request"

    token = doc["token"]
    s = requests.Session()
    vr = s.get(f"{BASE_URL}/api/auth/verify", params={"token": token},
               timeout=15, allow_redirects=False)
    assert vr.status_code in (200, 302, 303), f"verify failed: {vr.status_code} {vr.text}"
    assert "accent_session" in s.cookies, f"No accent_session cookie. Got: {s.cookies.get_dict()}"
    return s


def test_authenticated_pronounce_hits_claude(session_cookie):
    r = session_cookie.get(
        f"{BASE_URL}/api/pronounce",
        params={"word": "Vrelthanor"},
        timeout=45,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("source") == "llm", f"Expected source=llm, got {data}"
    ipa = data.get("ipa")
    assert isinstance(ipa, str) and len(ipa) > 0, f"Expected non-empty ipa, got {ipa!r}"


def test_caption_search_spelling_correction(session_cookie):
    r = session_cookie.get(
        f"{BASE_URL}/api/caption-search",
        params={"q": "Charlstn"},
        timeout=45,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("corrected_query") == "Charleston", f"Got: {data.get('corrected_query')!r} full={data}"


# --- Log verification ---
def test_backend_logs_show_anthropic_200_and_no_fallback():
    import glob
    logs = ""
    for p in sorted(glob.glob("/var/log/supervisor/backend.*.log")):
        try:
            logs += Path(p).read_text(errors="ignore")
        except FileNotFoundError:
            pass
    anthropic_200 = re.findall(r"api\.anthropic\.com.*HTTP/1\.1 200 OK", logs)
    assert anthropic_200, "No successful api.anthropic.com 200 lines in backend logs"
    # Only fail on Anthropic-specific auth errors, not ElevenLabs' auth errors
    # Anthropic returns 401 with body like {"error":{"type":"authentication_error"...
    # We scope by requiring 'anthropic' near the error.
    anthropic_auth_errs = re.findall(
        r"anthropic[^\n]{0,500}authentication_error|authentication_error[^\n]{0,500}anthropic",
        logs, re.IGNORECASE,
    )
    assert not anthropic_auth_errs, f"Anthropic authentication_error present: {anthropic_auth_errs[:2]}"
    assert "Emergent LLM call" not in logs, "Emergent fallback was used"
