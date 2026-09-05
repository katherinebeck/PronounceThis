"""Tests for the /api/tts SSML <phoneme> tag fix (CMU IPA lookup)."""
import base64
import os
import time

import pytest
import requests
from dotenv import load_dotenv

# Load env vars from backend/.env and frontend/.env
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env", override=False)

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _post_tts(session, word, timeout=60):
    return session.post(f"{API}/tts", json={"word": word}, timeout=timeout)


def _assert_valid_audio(resp, expected_word):
    assert resp.status_code == 200, f"body: {resp.text[:300]}"
    data = resp.json()
    assert data["word"] == expected_word
    assert isinstance(data["audio_b64"], str)
    assert len(data["audio_b64"]) > 100, "audio_b64 unexpectedly small"
    # Validate it is actually base64
    raw = base64.b64decode(data["audio_b64"])
    assert len(raw) > 500, f"decoded audio too small: {len(raw)} bytes"
    assert data["mime"] == "audio/mpeg"
    return data


# --- Core fix: CMU-known words go through the SSML <phoneme> tag path
@pytest.mark.parametrize(
    "word",
    ["direction", "popular", "either", "route", "aunt", "schedule"],
)
def test_tts_returns_audio_for_cmu_known_words(session, word):
    resp = _post_tts(session, word)
    _assert_valid_audio(resp, word)


# --- Edge case: CMU-unknown words must fall back to plain-text path (no crash)
@pytest.mark.parametrize("word", ["Whitmore", "Zzykx"])
def test_tts_falls_back_for_cmu_unknown_words(session, word):
    resp = _post_tts(session, word)
    _assert_valid_audio(resp, word)


# --- Regression: caching still works, and second call is fast
def test_tts_cache_second_call_is_cached_and_fast(session):
    # First call — may already be cached from earlier tests, that's fine.
    _post_tts(session, "direction")
    # Second call must report cached=true and be fast.
    t0 = time.time()
    resp = _post_tts(session, "direction")
    elapsed_ms = (time.time() - t0) * 1000
    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is True, f"expected cached=true, got {data}"
    assert len(data["audio_b64"]) > 100
    assert elapsed_ms < 2000, f"cached response too slow: {elapsed_ms:.0f}ms"


# --- Regression: empty word still returns 400
def test_tts_empty_word_returns_400(session):
    r = session.post(f"{API}/tts", json={"word": ""}, timeout=15)
    assert r.status_code == 400


# --- Sanity: confirm SSML phoneme path is reachable via phonetics helpers
def test_cmu_ipa_lookup_available_for_direction():
    """Direct check that the code path used inside /api/tts produces an IPA
    string for 'direction' — this is what gets wrapped in <phoneme>."""
    import sys
    sys.path.insert(0, "/app/backend")
    from phonetics import get_arpabet, arpabet_to_ipa
    arp = get_arpabet("direction")
    assert arp is not None and len(arp) > 0
    ipa = arpabet_to_ipa(arp)
    assert ipa and len(ipa) > 0
    # Must include the primary stress marker on the stressed vowel.
    assert "ˈ" in ipa


def test_cmu_ipa_lookup_none_for_unknown_word():
    import sys
    sys.path.insert(0, "/app/backend")
    from phonetics import get_arpabet
    assert get_arpabet("Zzykx") is None
