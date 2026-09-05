"""Tests for the Quota Safety Net feature:
- server._prewarm_proper_nouns background helper
- POST /api/scenes/upload enqueues prewarm as a BackgroundTask (non-blocking)
- CLI /app/backend/prewarm.py runs and detects quota exhaustion
"""
from __future__ import annotations

import asyncio
import io
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path
import types
from unittest.mock import patch

import pytest
from reportlab.pdfgen import canvas

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Module import + unit-level tests for _prewarm_proper_nouns
# ---------------------------------------------------------------------------

def test_server_imports_cleanly():
    """Import server.py — should not raise."""
    import server  # noqa: F401
    assert hasattr(server, "_prewarm_proper_nouns")
    assert hasattr(server, "upload_scene")


def test_prewarm_proper_nouns_calls_once_per_unique_word():
    import server

    calls: list[tuple[str, int]] = []

    async def fake_search(word, limit=6):
        calls.append((word, limit))
        return {"results": [], "cached": False}

    async def noop_sleep(_delay):
        return None

    fake_asyncio = types.SimpleNamespace(sleep=noop_sleep)

    words = ["Jane", "Mark", "Jane", "  ", "", "Mark", "Eliza"]
    with patch.object(server.caption_service, "search", side_effect=fake_search), \
         patch.object(server, "asyncio", fake_asyncio):
        asyncio.run(server._prewarm_proper_nouns(words))

    unique_called = {c[0] for c in calls}
    assert unique_called == {"Jane", "Mark", "Eliza"}, calls
    assert len(calls) == 3, f"expected exactly 3 calls (dedup); got {calls}"
    # All calls used limit=6 (proper noun default)
    assert all(c[1] == 6 for c in calls)


def test_prewarm_proper_nouns_sleeps_between_calls():
    """Should sleep ~0.5s between search calls to spare quota."""
    import server

    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    async def fake_search(word, limit=6):
        return {"results": []}

    with patch.object(server.caption_service, "search", side_effect=fake_search), \
         patch.object(server, "asyncio", types.SimpleNamespace(sleep=fake_sleep)):
        asyncio.run(server._prewarm_proper_nouns(["A", "B", "C"]))

    assert sleeps, "expected at least one sleep between prewarm calls"
    # server currently sleeps 0.5s per iteration (after each search)
    assert all(abs(s - 0.5) < 0.01 for s in sleeps), sleeps
    assert len(sleeps) == 3


def test_prewarm_proper_nouns_swallows_exceptions():
    """A failed caption search must NOT propagate — subsequent words continue."""
    import server

    calls: list[str] = []

    async def flaky_search(word, limit=6):
        calls.append(word)
        if word == "Boom":
            raise RuntimeError("simulated quota / network error")
        return {"results": []}

    async def noop_sleep(_delay):
        return None

    with patch.object(server.caption_service, "search", side_effect=flaky_search), \
         patch.object(server, "asyncio", types.SimpleNamespace(sleep=noop_sleep)):
        # Should not raise
        asyncio.run(server._prewarm_proper_nouns(["Ok1", "Boom", "Ok2"]))

    assert set(calls) == {"Ok1", "Boom", "Ok2"}, calls


def test_prewarm_proper_nouns_empty_list_noop():
    import server

    async def fake_search(*_a, **_k):
        raise AssertionError("should not be called for empty list")

    with patch.object(server.caption_service, "search", side_effect=fake_search):
        asyncio.run(server._prewarm_proper_nouns([]))
        asyncio.run(server._prewarm_proper_nouns(["", "   "]))


# ---------------------------------------------------------------------------
# Integration: POST /api/scenes/upload enqueues background task, non-blocking
# ---------------------------------------------------------------------------

def _make_pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.split(". "):
        c.drawString(72, y, line.strip())
        y -= 24
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
def sample_pdf():
    return _make_pdf_bytes(
        "JANE: I want a little butter on my bread, mother. "
        "MARK: Better hurry, darling. The water is getting cold."
    )


def test_upload_enqueues_prewarm_background_task_and_is_non_blocking(sample_pdf):
    """Upload should:
    - return 200 with a Scene body
    - schedule _prewarm_proper_nouns via BackgroundTasks (called once, args = proper_nouns)
    - NOT block the request on caption_service.search even if it sleeps 3s
    """
    import server
    from fastapi.testclient import TestClient

    # Speed up: bypass real LLM dialogue extraction. Return deterministic
    # proper nouns so we can assert the prewarm call payload precisely.
    proper_nouns_fixture = ["Jane", "Mark"]

    async def fake_build(raw_text):
        # (tokens, turns_public, dialogue, proper_nouns)
        return [], [], "JANE: hi.\nMARK: hi.", list(proper_nouns_fixture)

    # Capture background-task registrations WITHOUT running them, so we can
    # both (a) assert add_task was invoked and (b) prove the endpoint itself
    # doesn't inline-await caption_service.search.
    recorded_tasks: list[tuple] = []

    original_add_task = server.BackgroundTasks.add_task

    def spy_add_task(self, func, *a, **kw):
        recorded_tasks.append((func, a, kw))
        # deliberately do NOT call original — we don't want the task to run

    # A search fake that would take 3s if inlined — proves non-blocking.
    async def slow_search(word, limit=6):
        await asyncio.sleep(3.0)
        return {"results": []}

    with patch.object(server, "build_dialogue_only_scene", side_effect=fake_build), \
         patch.object(server.BackgroundTasks, "add_task", spy_add_task), \
         patch.object(server.caption_service, "search", side_effect=slow_search):

        client = TestClient(server.app)
        files = {"file": ("prewarm_test.pdf", sample_pdf, "application/pdf")}
        t0 = time.monotonic()
        r = client.post("/api/scenes/upload", files=files)
        elapsed = time.monotonic() - t0

    assert r.status_code == 200, r.text
    body = r.json()
    assert "id" in body and "tokens" in body and "turns" in body

    # Non-blocking assertion: request must return well under the 3s search sleep.
    assert elapsed < 2.0, (
        f"Upload response took {elapsed:.2f}s — appears to block on caption "
        "search. Background task should defer it past response send."
    )

    # Background task assertion: exactly one add_task with our helper + nouns.
    prewarm_calls = [t for t in recorded_tasks if t[0] is server._prewarm_proper_nouns]
    assert len(prewarm_calls) == 1, (
        f"expected 1 _prewarm_proper_nouns background task; recorded={recorded_tasks}"
    )
    _, args, _kw = prewarm_calls[0]
    assert list(args[0]) == proper_nouns_fixture, args

    # Cleanup Mongo doc
    try:
        client = TestClient(server.app)
        client.delete(f"/api/scenes/{body['id']}")
    except Exception:
        pass


def test_upload_no_prewarm_task_when_no_proper_nouns(sample_pdf):
    """If the scene has zero proper nouns, no background task is enqueued."""
    import server
    from fastapi.testclient import TestClient

    async def fake_build(raw_text):
        return [], [], "dialogue", []  # empty proper_nouns

    inserted: list[dict] = []

    class FakeScenes:
        async def insert_one(self, doc):
            inserted.append(doc)
            return types.SimpleNamespace(inserted_id="fake")
        async def delete_one(self, *a, **k):
            return types.SimpleNamespace(deleted_count=1)

    fake_db = types.SimpleNamespace(scenes=FakeScenes())

    recorded: list = []

    def spy_add_task(self, func, *a, **kw):
        recorded.append(func)

    with patch.object(server, "build_dialogue_only_scene", side_effect=fake_build), \
         patch.object(server.BackgroundTasks, "add_task", spy_add_task), \
         patch.object(server, "db", fake_db):
        client = TestClient(server.app)
        r = client.post(
            "/api/scenes/upload",
            files={"file": ("np.pdf", sample_pdf, "application/pdf")},
        )
    assert r.status_code == 200, r.text
    assert server._prewarm_proper_nouns not in recorded, recorded
    assert len(inserted) == 1


# ---------------------------------------------------------------------------
# CLI: /app/backend/prewarm.py
# ---------------------------------------------------------------------------

def test_prewarm_cli_runs_and_reports_loaded_words(tmp_path):
    """Run prewarm.py via subprocess with a stub caption_search that returns
    a canned result — verifies the wire-up (argparse, env checks, word file
    loader, logging) end-to-end without burning YouTube quota.
    """
    # Prepare a fake caption_search module that shadows the real one on sys.path.
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    (stub_dir / "caption_search.py").write_text(
        "class CaptionSearchService:\n"
        "    def __init__(self, db):\n"
        "        self.db = db\n"
        "    async def search(self, word, limit=6):\n"
        "        return {'query': word, 'results': [{'v': 'x'}], 'cached': False}\n"
    )

    # Word list with a few entries
    wf = tmp_path / "words.txt"
    wf.write_text("# comment\nhello\nworld\nfoo\nhello\n")

    env = os.environ.copy()
    # Put the stub dir FIRST on PYTHONPATH so it shadows the real caption_search.
    env["PYTHONPATH"] = f"{stub_dir}{os.pathsep}{BACKEND_DIR}{os.pathsep}" + env.get("PYTHONPATH", "")
    # Ensure required env vars exist for the CLI's guard clauses.
    env.setdefault("YOUTUBE_API_KEY", "test-key")
    assert env.get("MONGO_URL"), "MONGO_URL must be set for CLI test"
    assert env.get("DB_NAME"), "DB_NAME must be set for CLI test"

    proc = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "prewarm.py"),
         str(wf), "--limit", "3", "--delay", "0.1"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"prewarm exited {proc.returncode}\n{out}"
    assert "Loaded" in out and "words" in out, out
    # We wrote 3 unique words + a comment; limit=3 keeps all 3
    assert "Loaded 3 words" in out, out
    # Should have completed successfully — either fetched results or found the
    # cache already warm. Both are healthy success paths.
    lower = out.lower()
    assert (
        "results" in lower
        or "ok" in lower
        or "cache is warm" in lower
        or "done" in lower
    ), out


def test_prewarm_cli_missing_env_exits_nonzero(tmp_path):
    """CLI should exit non-zero if YOUTUBE_API_KEY is missing."""
    wf = tmp_path / "words.txt"
    wf.write_text("hello\n")

    env = os.environ.copy()
    env.pop("YOUTUBE_API_KEY", None)
    # Prevent falling back to python-dotenv reading backend/.env
    # by pointing HOME so load_dotenv still loads real .env — instead we
    # patch by giving the .env location no key. Simplest: intercept via
    # setting YOUTUBE_API_KEY to empty AFTER load_dotenv? That's tricky.
    # Fall back: skip this test if backend .env has the key set.
    envfile = BACKEND_DIR / ".env"
    if envfile.exists() and "YOUTUBE_API_KEY" in envfile.read_text():
        pytest.skip("backend/.env sets YOUTUBE_API_KEY; can't cleanly clear for CLI")

    proc = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "prewarm.py"), str(wf), "--limit", "1"],
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode != 0
    assert "YOUTUBE_API_KEY" in (proc.stdout + proc.stderr)


def test_prewarm_stops_early_on_quota_exceeded(tmp_path, monkeypatch):
    """When caption_search returns {'error': 'YouTube ... quota exceeded'},
    the CLI must set quota_hit, log 'YouTube quota exhausted', and skip
    remaining words. Run in-process by importing prewarm and monkeypatching."""
    # Import prewarm module in-process (already loads .env once)
    import importlib
    sys.path.insert(0, str(BACKEND_DIR))
    prewarm_mod = importlib.import_module("prewarm")

    class FakeCursor:
        def __init__(self, docs): self._docs = list(docs)
        def __aiter__(self): return self
        async def __anext__(self):
            if not self._docs:
                raise StopAsyncIteration
            return self._docs.pop(0)

    class FakeColl:
        def find(self, *a, **k): return FakeCursor([])

    class FakeDB:
        caption_search_cache = FakeColl()
        def __getitem__(self, k): return FakeColl()

    class FakeMongo:
        def __init__(self, url): pass
        def __getitem__(self, name): return FakeDB()
        def close(self): pass

    call_log: list[str] = []

    class QuotaSvc:
        def __init__(self, db): pass
        async def search(self, word, limit=6):
            call_log.append(word)
            return {
                "query": word, "results": [],
                "error": "YouTube daily search quota exceeded",
            }

    monkeypatch.setattr(prewarm_mod, "AsyncIOMotorClient", FakeMongo)
    monkeypatch.setattr(prewarm_mod, "CaptionSearchService", QuotaSvc)
    # Ensure env vars pass the CLI check
    monkeypatch.setenv("MONGO_URL", os.environ.get("MONGO_URL", "mongodb://x/"))
    monkeypatch.setenv("DB_NAME", os.environ.get("DB_NAME", "x"))
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    # Capture log messages
    import logging
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r.getMessage())
    prewarm_mod.log.addHandler(handler)
    try:
        asyncio.run(prewarm_mod.prewarm(
            ["one", "two", "three", "four"], concurrency=1, delay=0.0
        ))
    finally:
        prewarm_mod.log.removeHandler(handler)

    # After the first quota response, `quota_hit` becomes True — subsequent
    # iterations enter the semaphore and return immediately without calling
    # search. So exactly one search call is expected.
    assert len(call_log) == 1, f"expected 1 search before quota-stop; got {call_log}"
    quota_msg = [m for m in records if "quota exhausted" in m.lower()]
    assert quota_msg, f"expected 'quota exhausted' log; got {records}"
