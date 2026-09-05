"""CLI to pre-warm the caption-search cache for common English words + names.

Run periodically (e.g. every night after the YouTube quota resets at
midnight Pacific time) so students almost never trigger a fresh YouTube
API call on the words they look up most.

Usage:
    python -m prewarm                     # use bundled word list
    python -m prewarm words.txt          # use a custom list
    python -m prewarm --limit 100        # stop after N words (for a first run)

Reads /app/backend/data/prewarm_words.txt by default. One word per line;
blanks and lines starting with "#" are ignored. Skips words already cached
so subsequent runs cheaply top up the index.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load env before importing modules that read it.
load_dotenv(Path(__file__).with_name(".env"))

from caption_search import CaptionSearchService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prewarm")


def read_words(path: Path) -> list[str]:
    words: list[str] = []
    seen = set()
    for line in path.read_text().splitlines():
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        norm = s.lower()
        if norm in seen:
            continue
        seen.add(norm)
        words.append(s)
    return words


async def prewarm(words: list[str], concurrency: int = 1, delay: float = 1.0):
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ["DB_NAME"]]
    svc = CaptionSearchService(db)

    # Determine which words are already cached (skip them cheaply).
    cached_docs = db.caption_search_cache.find(
        {"query": {"$in": [w.lower() for w in words]}},
        {"query": 1, "expires_at": 1, "_id": 0},
    )
    now = time.time()
    cached_fresh = set()
    async for row in cached_docs:
        if row.get("expires_at", 0) > now and row.get("query"):
            cached_fresh.add(row["query"])

    todo = [w for w in words if w.lower() not in cached_fresh]
    log.info("Total %d words · %d already cached · %d to fetch",
             len(words), len(cached_fresh), len(todo))

    if not todo:
        log.info("Nothing to do — cache is warm.")
        mongo.close()
        return

    sem = asyncio.Semaphore(concurrency)
    started = time.time()
    successes = 0
    failures = 0
    quota_hit = False

    async def _one(idx: int, word: str) -> None:
        nonlocal successes, failures, quota_hit
        async with sem:
            if quota_hit:
                return
            try:
                res = await svc.search(word, limit=6)
            except Exception as exc:  # noqa: BLE001
                log.warning("[%d/%d] %r FAIL: %s", idx, len(todo), word, exc)
                failures += 1
                return
            got = len(res.get("results", []))
            err = res.get("error")
            if err and "quota" in err.lower():
                quota_hit = True
                log.error("YouTube quota exhausted after %d words. Stopping.", idx)
                return
            log.info("[%d/%d] %r ✔ %d results", idx, len(todo), word, got)
            successes += 1
            await asyncio.sleep(delay)

    await asyncio.gather(*[_one(i, w) for i, w in enumerate(todo, start=1)])
    elapsed = time.time() - started
    log.info("Done — %d ok, %d fail, %.1fs total", successes, failures, elapsed)
    mongo.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("word_file", nargs="?",
                   default=str(Path(__file__).parent / "data" / "prewarm_words.txt"))
    p.add_argument("--limit", type=int, default=0,
                   help="Cap the number of words fetched this run.")
    p.add_argument("--delay", type=float, default=1.0,
                   help="Seconds to sleep between requests.")
    args = p.parse_args()

    path = Path(args.word_file)
    if not path.exists():
        log.error("word list not found: %s", path)
        return 1
    words = read_words(path)
    if args.limit > 0:
        words = words[: args.limit]
    log.info("Loaded %d words from %s", len(words), path)

    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        log.error("MONGO_URL and DB_NAME must be set (backend/.env).")
        return 1
    if not os.environ.get("YOUTUBE_API_KEY"):
        log.error("YOUTUBE_API_KEY must be set (backend/.env).")
        return 1

    asyncio.run(prewarm(words, delay=args.delay))
    return 0


if __name__ == "__main__":
    sys.exit(main())
