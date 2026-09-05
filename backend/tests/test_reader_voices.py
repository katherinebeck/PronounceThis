"""Backend tests for Reader Voices + per-voice turn TTS caching.

Covers:
- GET /api/reader-voices returns Jessica + Adam
- POST /api/scenes/{id}/turns/{i}/tts (no voice) still works (regression)
- POST .../tts?voice=jessica generates audio, then is cached (cached=true)
- POST .../tts?voice=adam is cached separately from Jessica (different bytes)
- POST .../tts?voice=nonexistentvoice returns 400 Unknown voice.
"""
import io
import os

import pytest
import requests
from reportlab.pdfgen import canvas

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _pdf(lines):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for ln in lines:
        c.drawString(72, y, ln)
        y -= 24
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture(scope="module")
def session():
    return requests.Session()


@pytest.fixture(scope="module")
def scene(session):
    """Try existing scenes; fall back to uploading a new PDF."""
    r = session.get(f"{API}/scenes", timeout=30)
    assert r.status_code == 200
    scenes = r.json()
    for s in scenes:
        # need scene with at least one dialogue turn
        detail = session.get(f"{API}/scenes/{s['id']}", timeout=30).json()
        if detail.get("turns"):
            return detail
    # Upload a fresh scene
    lines = [
        "JANE: Hello there friend.",
        "MARK: How are you today.",
    ]
    files = {"file": ("rv.pdf", _pdf(lines), "application/pdf")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=180)
    assert r.status_code == 200, r.text
    return r.json()


# ---- /api/reader-voices ---------------------------------------------------
def test_reader_voices_list(session):
    r = session.get(f"{API}/reader-voices", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "voices" in data
    keys = [v["key"] for v in data["voices"]]
    assert "jessica" in keys
    assert "adam" in keys
    for v in data["voices"]:
        assert "label" in v and "gender" in v


# ---- Regression: existing turn-TTS (no voice) -----------------------------
def test_turn_tts_no_voice_still_works(session, scene):
    sid = scene["id"]
    r = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("audio_b64")
    assert len(data["audio_b64"]) > 100


# ---- voice=jessica caches ------------------------------------------------
def test_turn_tts_jessica_cache(session, scene):
    sid = scene["id"]
    r1 = session.post(f"{API}/scenes/{sid}/turns/0/tts",
                      params={"voice": "jessica"}, timeout=60)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["audio_b64"]

    r2 = session.post(f"{API}/scenes/{sid}/turns/0/tts",
                      params={"voice": "jessica"}, timeout=30)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["cached"] is True
    assert d2["audio_b64"] == d1["audio_b64"]


# ---- voice=adam separate cache & different audio -------------------------
def test_turn_tts_adam_separate_cache(session, scene):
    sid = scene["id"]
    # Fetch jessica first (may already be cached from prior test)
    rj = session.post(f"{API}/scenes/{sid}/turns/0/tts",
                      params={"voice": "jessica"}, timeout=60)
    assert rj.status_code == 200
    jessica_b64 = rj.json()["audio_b64"]

    ra1 = session.post(f"{API}/scenes/{sid}/turns/0/tts",
                       params={"voice": "adam"}, timeout=60)
    assert ra1.status_code == 200, ra1.text
    d_adam1 = ra1.json()
    assert d_adam1["audio_b64"]
    # First adam call should NOT be cached (fresh voice)
    assert d_adam1["cached"] is False

    # Different voice => different audio bytes
    assert d_adam1["audio_b64"] != jessica_b64

    # Second call cached
    ra2 = session.post(f"{API}/scenes/{sid}/turns/0/tts",
                       params={"voice": "adam"}, timeout=30)
    assert ra2.status_code == 200
    assert ra2.json()["cached"] is True


# ---- unknown voice -> 400 -------------------------------------------------
def test_turn_tts_unknown_voice_400(session, scene):
    sid = scene["id"]
    r = session.post(f"{API}/scenes/{sid}/turns/0/tts",
                     params={"voice": "nonexistentvoice"}, timeout=15)
    assert r.status_code == 400
    assert r.json().get("detail") == "Unknown voice."
