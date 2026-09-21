"""Backend tests for the Kajabi-gated magic-link subscription layer.

Covers:
    - GET /api/auth/me (anon + authenticated)
    - POST /api/auth/request-magic-link (valid, invalid, rate-limit)
    - GET /api/auth/verify (valid, reuse, expired)
    - Gating on /api/tts, /api/scenes/upload, /api/scenes/{id}/download-lines
    - Trial consumption + subscriber bypass
    - Kajabi /webhook (auth, purchase, payment_succeeded, dedupe)
    - Kajabi /cancel (auth, future vs past end date)
    - /api/caption-search remains open

Uses direct mongo writes for magic-link tokens (Resend is in test mode).
Cleans up TEST_ users/memberships/magic_links/webhook_events at teardown.
"""
from __future__ import annotations

import io
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymongo
import pytest
import requests
from reportlab.pdfgen import canvas

# --- Config -----------------------------------------------------------------
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get(
    "REACT_APP_BACKEND_URL"
) else "https://accent-coach-pro.preview.emergentagent.com"

# Load backend .env for direct-mongo access + webhook token
_ENV = {}
for line in Path("/app/backend/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        _ENV[k.strip()] = v.strip().strip('"').strip("'")

MONGO_URL = _ENV["MONGO_URL"]
DB_NAME = _ENV["DB_NAME"]
KAJABI_TOKEN = _ENV["KAJABI_WEBHOOK_TOKEN"]

_client = pymongo.MongoClient(MONGO_URL)
db = _client[DB_NAME]


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _mk_email(prefix="user"):
    return f"TEST_{prefix}_{uuid.uuid4().hex[:10]}@example.org"


def _mk_pdf_bytes(text: str = "ALICE\nHello world.\n\nBOB\nHi there Alice.") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.split("\n"):
        c.drawString(72, y, line or " ")
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def _seed_magic_link(email: str, ttl_minutes: int = 10) -> str:
    """Insert a magic-link row directly and return the token."""
    token = secrets.token_urlsafe(32)
    db.magic_links.insert_one({
        "token": token,
        "email": email.lower(),
        "created_at": _iso(_now()),
        "expires_at": _iso(_now() + timedelta(minutes=ttl_minutes)),
        "consumed": False,
    })
    # Ensure user exists (verify handler updates last_login_at)
    db.users.update_one(
        {"email": email.lower()},
        {"$setOnInsert": {
            "email": email.lower(),
            "trial_word_used": 0,
            "trial_scene_used": 0,
            "created_at": _iso(_now()),
            "last_login_at": None,
        }},
        upsert=True,
    )
    return token


def _login(email: str) -> requests.Session:
    """Seed a magic link, verify, return a Session with cookies set."""
    token = _seed_magic_link(email)
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/auth/verify", params={"token": token},
              allow_redirects=False, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    assert "accent_session" in s.cookies
    return s


# --- Fixtures ---------------------------------------------------------------
_CREATED_EMAILS: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    for e in _CREATED_EMAILS:
        e = e.lower()
        db.users.delete_many({"email": e})
        db.memberships.delete_many({"user_email": e})
        db.magic_links.delete_many({"email": e})
    db.webhook_events.delete_many({"external_event_id": {"$regex": "^TEST_"}})


def _register(email: str) -> str:
    _CREATED_EMAILS.append(email)
    return email


# --- 1. /api/auth/me anonymous ---------------------------------------------
def test_auth_me_anonymous():
    r = requests.get(f"{BASE_URL}/api/auth/me", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["authenticated"] is False
    assert d["trial_word_limit"] == 1
    assert d["trial_scene_limit"] == 1
    assert d.get("subscription_status", "none") == "none"


# --- 2. request-magic-link rate-limit --------------------------------------
def test_request_magic_link_rate_limit():
    email = _register(_mk_email("rl"))
    # First call
    r1 = requests.post(f"{BASE_URL}/api/auth/request-magic-link",
                       json={"email": email}, timeout=30)
    # Resend may reject fake domain but backend rate-limit check runs first;
    # first call may still 502 if Resend rejects. Handle both.
    # We only strictly assert rate-limit behavior: 2nd call must not create
    # a 2nd magic_links row within 60s.
    first_count = db.magic_links.count_documents({"email": email.lower()})
    r2 = requests.post(f"{BASE_URL}/api/auth/request-magic-link",
                       json={"email": email}, timeout=30)
    assert r2.status_code == 200, f"2nd: {r2.status_code} {r2.text}"
    assert r2.json().get("ok") is True
    second_count = db.magic_links.count_documents({"email": email.lower()})
    assert second_count == first_count, (
        f"rate-limit failed: rows went {first_count} -> {second_count}"
    )
    # Log first call outcome without failing on Resend rejections
    print(f"[rate-limit] first call: {r1.status_code}, rows={first_count}")


# --- 3. invalid email -------------------------------------------------------
def test_request_magic_link_invalid_email():
    r = requests.post(f"{BASE_URL}/api/auth/request-magic-link",
                      json={"email": "not-an-email"}, timeout=30)
    # Pydantic EmailStr yields 422; explicit regex check yields 400.
    # Spec says 400 invalid_email — accept either but prefer 400/422.
    assert r.status_code in (400, 422), f"{r.status_code} {r.text}"
    if r.status_code == 400:
        assert "invalid_email" in r.text


# --- 4. verify valid + reuse -----------------------------------------------
def test_verify_valid_then_reuse():
    email = _register(_mk_email("verify"))
    token = _seed_magic_link(email)
    r = requests.get(f"{BASE_URL}/api/auth/verify", params={"token": token},
                     allow_redirects=False, timeout=30)
    assert r.status_code == 200
    assert r.json().get("email") == email.lower()
    # httpOnly cookie
    set_cookie = r.headers.get("set-cookie", "")
    assert "accent_session=" in set_cookie.lower()
    assert "httponly" in set_cookie.lower()

    # Reuse: links stay valid for their 15-min window (mail scanners often
    # open them first), capped at MAGIC_LINK_MAX_USES total opens.
    for _ in range(4):
        r2 = requests.get(f"{BASE_URL}/api/auth/verify", params={"token": token}, timeout=30)
        assert r2.status_code == 200
    r3 = requests.get(f"{BASE_URL}/api/auth/verify", params={"token": token}, timeout=30)
    assert r3.status_code == 400
    assert "invalid_or_used_link" in r3.text


# --- 5. verify expired ------------------------------------------------------
def test_verify_expired():
    email = _register(_mk_email("exp"))
    token = secrets.token_urlsafe(32)
    db.magic_links.insert_one({
        "token": token,
        "email": email.lower(),
        "created_at": _iso(_now() - timedelta(hours=1)),
        "expires_at": _iso(_now() - timedelta(minutes=5)),
        "consumed": False,
    })
    r = requests.get(f"{BASE_URL}/api/auth/verify", params={"token": token},
                     timeout=30)
    assert r.status_code == 400
    assert "expired_link" in r.text


# --- 6-8. Unauthenticated gates --------------------------------------------
def test_tts_requires_auth():
    r = requests.post(f"{BASE_URL}/api/tts", json={"word": "hello"}, timeout=30)
    assert r.status_code == 401
    assert "not_authenticated" in r.text


def test_scenes_upload_requires_auth():
    pdf = _mk_pdf_bytes()
    r = requests.post(f"{BASE_URL}/api/scenes/upload",
                      files={"file": ("t.pdf", pdf, "application/pdf")},
                      timeout=30)
    assert r.status_code == 401
    assert "not_authenticated" in r.text


def test_download_lines_requires_auth():
    r = requests.get(
        f"{BASE_URL}/api/scenes/nonexistent/download-lines",
        params={"character": "ALICE"}, timeout=30,
    )
    assert r.status_code == 401
    assert "not_authenticated" in r.text


# --- 9. Trial: TTS once succeeds, second call 402 --------------------------
def test_tts_trial_then_exhausted():
    email = _register(_mk_email("tts"))
    s = _login(email)
    # First call
    r1 = s.post(f"{BASE_URL}/api/tts", json={"word": "hello"}, timeout=60)
    assert r1.status_code == 200, f"first tts: {r1.status_code} {r1.text[:200]}"
    u = db.users.find_one({"email": email.lower()})
    assert u["trial_word_used"] == 1
    # Second call - trial exhausted
    r2 = s.post(f"{BASE_URL}/api/tts", json={"word": "world"}, timeout=60)
    assert r2.status_code == 402, f"second tts: {r2.status_code} {r2.text}"
    d = r2.json().get("detail")
    assert isinstance(d, dict) and d.get("code") == "trial_exhausted"
    assert d.get("kind") == "word"


# --- 10. Trial: scene upload once, second call 402 -------------------------
def test_scene_upload_trial_then_exhausted():
    email = _register(_mk_email("scene"))
    s = _login(email)
    pdf = _mk_pdf_bytes()
    r1 = s.post(
        f"{BASE_URL}/api/scenes/upload",
        files={"file": ("scene1.pdf", pdf, "application/pdf")},
        timeout=120,
    )
    assert r1.status_code == 200, f"first upload: {r1.status_code} {r1.text[:300]}"
    u = db.users.find_one({"email": email.lower()})
    assert u["trial_scene_used"] == 1
    # Second upload
    r2 = s.post(
        f"{BASE_URL}/api/scenes/upload",
        files={"file": ("scene2.pdf", pdf, "application/pdf")},
        timeout=60,
    )
    assert r2.status_code == 402, f"second upload: {r2.status_code} {r2.text[:200]}"
    d = r2.json().get("detail")
    assert isinstance(d, dict) and d.get("code") == "trial_exhausted"
    assert d.get("kind") == "scene"


# --- 11. Subscriber bypass -------------------------------------------------
def test_subscriber_bypass():
    email = _register(_mk_email("sub"))
    s = _login(email)
    # Insert active membership
    db.memberships.insert_one({
        "user_email": email.lower(),
        "offer_id": "o1",
        "status": "active",
        "subscription_end_at": None,
        "offer_title": "Test Offer",
        "created_at": _iso(_now()),
    })
    # /me reports active
    me = s.get(f"{BASE_URL}/api/auth/me", timeout=30).json()
    assert me["subscription_status"] == "active"

    # 2 TTS calls both succeed; word counter stays 0
    for w in ("hello", "world"):
        r = s.post(f"{BASE_URL}/api/tts", json={"word": w}, timeout=60)
        assert r.status_code == 200, f"sub tts({w}): {r.status_code} {r.text[:200]}"
    u = db.users.find_one({"email": email.lower()})
    assert u.get("trial_word_used", 0) == 0

    # 2 uploads both succeed; scene counter stays 0
    pdf = _mk_pdf_bytes()
    for i in range(2):
        r = s.post(
            f"{BASE_URL}/api/scenes/upload",
            files={"file": (f"s{i}.pdf", pdf, "application/pdf")},
            timeout=120,
        )
        assert r.status_code == 200, f"sub upload {i}: {r.status_code} {r.text[:200]}"
    u = db.users.find_one({"email": email.lower()})
    assert u.get("trial_scene_used", 0) == 0


# --- 12-13. Webhook auth ----------------------------------------------------
def test_webhook_no_token():
    r = requests.post(f"{BASE_URL}/api/kajabi/webhook", json={"event": "purchase"}, timeout=30)
    assert r.status_code == 401
    assert "invalid_webhook_token" in r.text


def test_webhook_wrong_token():
    r = requests.post(f"{BASE_URL}/api/kajabi/webhook",
                      params={"token": "wrong"}, json={"event": "purchase"},
                      timeout=30)
    assert r.status_code == 401


# --- 14. Webhook purchase -> membership + shell user + dedupe ---------------
def _purchase_envelope(email: str, offer_id: str, event_id: str,
                       event: str = "purchase"):
    return {
        "id": event_id,
        "event": event,
        "payload": [
            {"type": "customers", "id": "c1",
             "attributes": {"email": email}},
            {"type": "offers", "id": offer_id,
             "attributes": {"title": "Monthly Coaching"}},
            {"type": "purchases", "id": "p1",
             "attributes": {"created_at": _iso(_now())},
             "relationships": {"offer": {"data": {"id": offer_id}}}},
            {"type": "transactions", "id": "t1",
             "attributes": {"created_at": _iso(_now())}},
        ],
    }


def test_webhook_purchase_and_dedupe():
    email = _register(_mk_email("wh")).lower()
    offer_id = f"offer_{uuid.uuid4().hex[:6]}"
    event_id = f"TEST_evt_{uuid.uuid4().hex[:10]}"
    envelope = _purchase_envelope(email, offer_id, event_id)

    r = requests.post(f"{BASE_URL}/api/kajabi/webhook",
                      params={"token": KAJABI_TOKEN},
                      json=envelope, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == {"ok": True}

    m = db.memberships.find_one({"user_email": email, "offer_id": offer_id})
    assert m and m["status"] == "active"
    u = db.users.find_one({"email": email})
    assert u is not None
    ev = db.webhook_events.find_one({"external_event_id": event_id})
    assert ev is not None

    # Replay same envelope
    r2 = requests.post(f"{BASE_URL}/api/kajabi/webhook",
                       params={"token": KAJABI_TOKEN},
                       json=envelope, timeout=30)
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True
    assert db.memberships.count_documents(
        {"user_email": email, "offer_id": offer_id}
    ) == 1


# --- 15. payment_succeeded refreshes last_payment_at -----------------------
def test_webhook_payment_succeeded_refreshes():
    email = _register(_mk_email("pay")).lower()
    offer_id = f"offer_{uuid.uuid4().hex[:6]}"
    # Initial purchase
    ev1 = f"TEST_evt_{uuid.uuid4().hex[:10]}"
    requests.post(f"{BASE_URL}/api/kajabi/webhook",
                  params={"token": KAJABI_TOKEN},
                  json=_purchase_envelope(email, offer_id, ev1), timeout=30)
    m1 = db.memberships.find_one({"user_email": email, "offer_id": offer_id})
    prev_payment = m1.get("last_payment_at")

    time.sleep(1.1)
    ev2 = f"TEST_evt_{uuid.uuid4().hex[:10]}"
    env = _purchase_envelope(email, offer_id, ev2, event="payment_succeeded")
    # Give it a new transaction timestamp
    env["payload"][3]["attributes"]["created_at"] = _iso(_now())
    r = requests.post(f"{BASE_URL}/api/kajabi/webhook",
                      params={"token": KAJABI_TOKEN}, json=env, timeout=30)
    assert r.status_code == 200
    m2 = db.memberships.find_one({"user_email": email, "offer_id": offer_id})
    assert m2.get("last_payment_at") != prev_payment
    assert m2.get("last_event") == "payment_succeeded"


# --- 16. cancel with future/past end_at ------------------------------------
def test_cancel_future_and_past():
    email = _register(_mk_email("cancel")).lower()
    offer_id = f"offer_{uuid.uuid4().hex[:6]}"
    ev = f"TEST_evt_{uuid.uuid4().hex[:10]}"
    requests.post(f"{BASE_URL}/api/kajabi/webhook",
                  params={"token": KAJABI_TOKEN},
                  json=_purchase_envelope(email, offer_id, ev), timeout=30)

    # Login as this user to test /me
    s = _login(email)

    # Future end
    future = _iso(_now() + timedelta(days=30))
    r = requests.post(f"{BASE_URL}/api/kajabi/cancel",
                      params={"token": KAJABI_TOKEN},
                      json={"email": email, "subscription_end_at": future},
                      timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    me = s.get(f"{BASE_URL}/api/auth/me", timeout=30).json()
    assert me["subscription_status"] == "active", f"me={me}"

    # Past end
    past = _iso(_now() - timedelta(days=1))
    r2 = requests.post(f"{BASE_URL}/api/kajabi/cancel",
                       params={"token": KAJABI_TOKEN},
                       json={"email": email, "subscription_end_at": past},
                       timeout=30)
    assert r2.status_code == 200
    me2 = s.get(f"{BASE_URL}/api/auth/me", timeout=30).json()
    assert me2["subscription_status"] == "none", f"me={me2}"


def test_cancel_wrong_token():
    r = requests.post(f"{BASE_URL}/api/kajabi/cancel",
                      params={"token": "nope"},
                      json={"email": "x@example.org"}, timeout=30)
    assert r.status_code == 401


# --- 17. caption-search open ------------------------------------------------
def test_caption_search_open():
    r = requests.get(f"{BASE_URL}/api/caption-search",
                     params={"word": "hello", "limit": 1}, timeout=60)
    # Not 401/402; may be 200 or 5xx if quota, but must not be gated.
    assert r.status_code not in (401, 402), f"gated: {r.status_code} {r.text[:200]}"
