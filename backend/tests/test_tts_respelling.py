"""Tests for the /api/tts ARPABET-respelling fix (iteration 9).

The previous SSML <phoneme> fix (iteration 8) produced silent/broken audio
(~6-7KB) because eleven_multilingual_v2 does NOT support SSML phoneme tags.
This iteration replaces SSML with an English-readable respelling like
"duh-REK-shun" — plain text that the model reads phonetically and produces
a normal-length MP3 (>12KB for single words).
"""
import base64
import os
import sys
import time

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env", override=False)

sys.path.insert(0, "/app/backend")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MIN_REAL_AUDIO_BYTES = 12000  # anything smaller means the SSML-silent regression
MIN_ANY_AUDIO_BYTES = 4000    # graceful fallback words (Zzykx) still audible


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _post_tts(session, word, timeout=90):
    return session.post(f"{API}/tts", json={"word": word}, timeout=timeout)


def _decoded_len(data):
    return len(base64.b64decode(data["audio_b64"]))


# ---- UNIT: arpabet_to_respelling ------------------------------------------
class TestArpabetToRespelling:
    def test_direction_has_uppercase_stressed_syllable(self):
        from phonetics import arpabet_to_respelling
        out = arpabet_to_respelling(["D", "ER0", "EH1", "K", "SH", "AH0", "N"])
        assert isinstance(out, str) and out
        # Primary-stress syllable must be uppercase.
        assert any(c.isupper() for c in out)
        # Should contain either the EHKSH cluster or an EK-like cluster in caps.
        upper = out.upper()
        assert "EHKSH" in upper or "EK" in upper, f"got: {out}"

    def test_empty_returns_empty_string(self):
        from phonetics import arpabet_to_respelling
        assert arpabet_to_respelling([]) == ""

    def test_never_raises_for_wellformed_arpabet(self):
        from phonetics import arpabet_to_respelling, get_arpabet
        # Try a bunch of real words + a purely-consonant edge case.
        for w in ["direction", "popular", "either", "route", "aunt",
                  "february", "water", "beautiful", "schedule", "cat",
                  "a", "the", "rhythm"]:
            arp = get_arpabet(w)
            if arp is None:
                continue
            out = arpabet_to_respelling(arp)
            assert isinstance(out, str)


# ---- BUG FIX PRIMARY: /api/tts returns non-silent audio for 'direction'
def test_tts_direction_returns_full_length_audio(session):
    resp = _post_tts(session, "direction")
    assert resp.status_code == 200, resp.text[:300]
    data = resp.json()
    assert data["word"] == "direction"
    n = _decoded_len(data)
    assert n > MIN_REAL_AUDIO_BYTES, (
        f"decoded audio too small ({n} bytes) — SSML-silent regression?"
    )


# ---- BUG FIX BROADER: same for all commonly-mispronounced CMU-known words
@pytest.mark.parametrize(
    "word",
    ["direction", "popular", "either", "route", "aunt",
     "February", "water", "beautiful", "schedule"],
)
def test_tts_full_length_for_cmu_known_words(session, word):
    resp = _post_tts(session, word)
    assert resp.status_code == 200, resp.text[:300]
    data = resp.json()
    assert data["word"] == word
    assert data["mime"] == "audio/mpeg"
    n = _decoded_len(data)
    assert n > MIN_REAL_AUDIO_BYTES, (
        f"{word!r}: decoded audio too small ({n} bytes) — silent regression?"
    )


# ---- BUG FIX EDGE: CMU-unknown words gracefully fall through ---------------
@pytest.mark.parametrize("word", ["Zzykx", "Blorgnaxxle"])
def test_tts_unknown_word_falls_through(session, word):
    resp = _post_tts(session, word)
    assert resp.status_code == 200, resp.text[:300]
    data = resp.json()
    assert data["word"] == word
    n = _decoded_len(data)
    assert n > MIN_ANY_AUDIO_BYTES, f"{word!r}: audio suspiciously small ({n})"


# ---- REGRESSION: caching --------------------------------------------------
def test_tts_cache_second_call_fast(session):
    _post_tts(session, "direction")  # warm
    t0 = time.time()
    resp = _post_tts(session, "direction")
    elapsed_ms = (time.time() - t0) * 1000
    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is True, f"expected cached=true, got {data}"
    assert elapsed_ms < 2000, f"cached response too slow: {elapsed_ms:.0f}ms"
