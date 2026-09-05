"""Tests for the expanded CURATED_HANDLES list (37 channels) in
/app/backend/caption_search.py.

Verifies:
- >=25 of the 37 curated handles resolve to a channelId (via Mongo cache
  populated by a live search call).
- A common word ('president') returns >=3 results across >=2 channels.
- Baseline query ('hello') returns >=1 result OR gracefully returns empty
  (quota_exceeded is acceptable per review request).
- Nonsense query returns [] without crashing.
- Result shape includes video_id, channel_title, offset_seconds, has_timestamp.
"""
import os
import sys
import time
import requests
import pytest

# Import CURATED_HANDLES to know current expected size.
sys.path.insert(0, "/app/backend")
from caption_search import CURATED_HANDLES  # noqa: E402

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

REQUIRED_KEYS = {
    "video_id", "title", "channel_title",
    "offset_seconds", "snippet", "youtube_url", "has_timestamp",
}


def _get(q, refresh=False, timeout=90):
    params = {"q": q}
    if refresh:
        params["refresh"] = "true"
    return requests.get(f"{BASE_URL}/api/caption-search",
                        params=params, timeout=timeout)


class TestExpandedCuratedList:
    def test_curated_handles_expanded(self):
        """Sanity: the list is expanded to ~37 entries (>=30)."""
        assert len(CURATED_HANDLES) >= 30, (
            f"Expected >=30 curated handles, got {len(CURATED_HANDLES)}"
        )

    def test_president_returns_results_across_channels(self):
        """Common query should hit multiple curated channels after
        the pool expansion. Uses refresh=true (1 of the 3-query budget)."""
        r = _get("president", refresh=True, timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        # Graceful quota-exceeded response is acceptable.
        if data.get("error") and "quota" in data["error"].lower():
            pytest.skip(f"YouTube quota exhausted: {data['error']}")
        results = data.get("results", [])
        assert len(results) >= 3, f"Expected >=3 results, got {len(results)}"
        channels = {r_["channel_title"] for r_ in results}
        assert len(channels) >= 2, (
            f"Expected >=2 distinct channels, got {channels}"
        )
        # Result shape.
        for item in results:
            missing = REQUIRED_KEYS - set(item.keys())
            assert not missing, f"missing keys: {missing}"

    def test_hello_baseline_coverage(self):
        """'hello' with refresh=true should ideally return >=1 result.
        Empty is not a hard fail per review request. Uses budget slot 2."""
        r = _get("hello", refresh=True, timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        if data.get("error") and "quota" in data["error"].lower():
            pytest.skip(f"YouTube quota exhausted: {data['error']}")
        # Soft assertion — log rather than fail if 0.
        n = len(data.get("results", []))
        assert n >= 0, "should not crash"
        if n == 0:
            print("WARNING: 'hello' returned 0 results even with refresh=true")

    def test_nonsense_query_empty_no_crash(self):
        """Gibberish should return 0 results (or quota err) but never crash."""
        r = _get("xyzzzznonsense", refresh=False, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("results", []), list)
        # After 'president' warmed the channel cache, results should just be [].
        if not (data.get("error") and "quota" in data["error"].lower()):
            assert data["results"] == [], (
                f"Expected empty results for nonsense, got {data['results']}"
            )

    def test_channel_cache_populated(self):
        """Verify >=25 of the 37 handles resolved to channelIds in Mongo.
        Reads directly from the caption_channel_cache collection."""
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio

        async def _count():
            mongo_url = os.environ["MONGO_URL"]
            db_name = os.environ["DB_NAME"]
            client = AsyncIOMotorClient(mongo_url)
            db = client[db_name]
            cursor = db.caption_channel_cache.find(
                {"channel_id": {"$exists": True, "$ne": None}}
            )
            docs = await cursor.to_list(length=200)
            client.close()
            return docs

        docs = asyncio.run(_count())
        resolved = {d["handle"].lower() for d in docs if d.get("channel_id")}
        expected_handles = {h["handle"].lower() for h in CURATED_HANDLES}
        overlap = resolved & expected_handles
        print(f"Resolved {len(overlap)}/{len(expected_handles)} curated handles")
        print(f"Missing: {sorted(expected_handles - resolved)}")
        assert len(overlap) >= 25, (
            f"Only {len(overlap)}/{len(expected_handles)} handles resolved "
            f"(expected >=25). Missing: {sorted(expected_handles - resolved)}"
        )

    def test_no_regression_result_fields(self):
        """Re-run cached 'president' — ensures cache path returns full shape."""
        r = _get("president", refresh=False, timeout=30)
        assert r.status_code == 200
        data = r.json()
        if data.get("error") and "quota" in data["error"].lower():
            pytest.skip("quota exceeded")
        for item in data.get("results", []):
            assert "video_id" in item
            assert "channel_title" in item
            assert "offset_seconds" in item
            assert "has_timestamp" in item
            assert isinstance(item["has_timestamp"], bool)

    def test_cache_hit_is_fast(self):
        """Cached 'president' second call should be <1s."""
        _get("president", timeout=30)  # warm
        t0 = time.time()
        r = _get("president", timeout=15)
        dt = time.time() - t0
        assert r.status_code == 200
        data = r.json()
        if data.get("cached") is True:
            assert dt < 1.5, f"cached call took {dt:.2f}s"
