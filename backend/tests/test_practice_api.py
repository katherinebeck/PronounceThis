# Practice (Practise This Word) API regression tests — cheap checks, no Azure calls except none.
import io
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from auth import _issue_jwt  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
COOKIE = {"accent_session": _issue_jwt("katherine@katherinebeck.com")}


# Status endpoint
def test_status_enabled():
    r = requests.get(f"{BASE_URL}/api/practice/status", timeout=20)
    assert r.status_code == 200
    assert r.json() == {"enabled": True, "locked": False}


# Auth required
def test_assess_no_auth_401():
    r = requests.post(f"{BASE_URL}/api/practice/assess", data={"word": "party"},
                      files={"audio": ("t.wav", io.BytesIO(b"x" * 500), "audio/wav")}, timeout=20)
    assert r.status_code == 401


# Invalid word validation
def test_assess_invalid_word_400():
    r = requests.post(f"{BASE_URL}/api/practice/assess", data={"word": "bad!!"}, cookies=COOKIE,
                      files={"audio": ("t.wav", io.BytesIO(b"x" * 500), "audio/wav")}, timeout=20)
    assert r.status_code == 400
    assert r.json()["detail"] == "Please search for a word first."


# Missing audio field -> 422
def test_assess_missing_audio_422():
    r = requests.post(f"{BASE_URL}/api/practice/assess", data={"word": "party"}, cookies=COOKIE, timeout=20)
    assert r.status_code == 422


# Rate limit: tiny (<200 byte) takes are rejected before Azure but still count → 429 within 21 calls
def test_rate_limit_429():
    codes = []
    for _ in range(22):
        r = requests.post(f"{BASE_URL}/api/practice/assess", data={"word": "party"}, cookies=COOKIE,
                          files={"audio": ("t.wav", io.BytesIO(b"x" * 50), "audio/wav")}, timeout=20)
        codes.append(r.status_code)
        if r.status_code == 429:
            break
    print(codes)
    assert 400 in codes
    assert codes[-1] == 429
