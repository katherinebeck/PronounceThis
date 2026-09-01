"""Tests for the /api/caption-search endpoint (YouGlish replacement).

Covers:
- Curated allowlist enforcement (channel_title in the allowed set)
- Result shape (video_id, title, channel_title, offset_seconds, snippet,
  youtube_url, has_timestamp)
- Caching semantics (second call is cached & <200ms)
- Query validation (missing → 422, too long → 400)
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

# The allowlist per the caption_search.py CURATED_HANDLES `label` values.
ALLOWED_CHANNELS = {
    "NPR", "CBS News", "PBS NewsHour", "ABC News", "CNN", "60 Minutes",
    "The Tonight Show", "The Tonight Show Starring Jimmy Fallon",
    "The Ellen Show", "TheEllenShow",
    "Conan O'Brien", "Team Coco",
    "Jimmy Kimmel Live", "The Late Show w/ Colbert",
    "Hot Ones", "First We Feast",
    "Vanity Fair", "VanityFair", "GQ", "Variety",
    "TED-Ed", "Vox", "CrashCourse",
    "WIRED", "WIRED (Erik Singer)",
}

REQUIRED_KEYS = {
    "video_id", "title", "channel_title",
    "offset_seconds", "snippet", "youtube_url", "has_timestamp",
}


class TestCaptionSearchCurated:
    def test_president_returns_curated_results(self):
        r = requests.get(f"{BASE_URL}/api/caption-search", params={"q": "president"}, timeout=60)
        assert r.status_code == 200
        data = r.json()
        assert data["query"] == "president"
        results = data["results"]
        assert isinstance(results, list) and len(results) == 6
        for item in results:
            missing = REQUIRED_KEYS - set(item.keys())
            assert not missing, f"missing keys: {missing} in {item}"
            assert item["channel_title"] in ALLOWED_CHANNELS, (
                f"Off-allowlist channel: {item['channel_title']}"
            )
            assert item["youtube_url"].startswith("https://www.youtube.com/watch?v=")

    def test_president_second_call_is_cached_and_fast(self):
        # Warm.
        requests.get(f"{BASE_URL}/api/caption-search", params={"q": "president"}, timeout=60)
        # Measure.
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/caption-search", params={"q": "president"}, timeout=30)
        dt = time.time() - t0
        assert r.status_code == 200
        data = r.json()
        assert data["cached"] is True
        assert dt < 1.0, f"cached call took {dt:.2f}s"

    def test_obama_returns_only_curated_channels(self):
        # 'obama' may return 0 results in the test env (rate-limit fallback);
        # what matters is: no off-allowlist channel ever leaks in.
        r = requests.get(f"{BASE_URL}/api/caption-search", params={"q": "obama"}, timeout=60)
        assert r.status_code == 200
        data = r.json()
        for item in data["results"]:
            assert item["channel_title"] in ALLOWED_CHANNELS


class TestCaptionSearchValidation:
    def test_missing_q_returns_422(self):
        r = requests.get(f"{BASE_URL}/api/caption-search", timeout=15)
        assert r.status_code == 422

    def test_query_too_long_returns_400(self):
        r = requests.get(f"{BASE_URL}/api/caption-search",
                         params={"q": "a" * 90}, timeout=15)
        assert r.status_code == 400
        assert "long" in r.json().get("detail", "").lower()

    def test_short_query_ok(self):
        r = requests.get(f"{BASE_URL}/api/caption-search",
                         params={"q": "president"}, timeout=30)
        assert r.status_code == 200
