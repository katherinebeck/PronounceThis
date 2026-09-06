"""Custom caption-search for the Accent Coach app.

Replaces the YouGlish widget with our own YouTube-caption-driven search,
restricted to a curated set of channels whose speakers are American English
natives (news anchors, US late-night hosts, dialect coaches, etc.).

Flow:
1. YouTube Data API v3 search for the word (US region, English relevance)
2. Post-filter results to the curated channel allowlist
3. Fetch each candidate's captions via `youtube-transcript-api`
4. Locate the word in the transcript, extract the timestamp
5. Return a list of {video_id, title, channel, offset_seconds, snippet}

Results are cached in Mongo for 24h keyed by the normalized word so repeat
queries cost zero YouTube quota.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import yt_dlp

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Curated allowlist of American-speaker YouTube channels. We resolve @handle
# -> channelId at runtime (and cache) so we don't hard-code potentially stale
# ids. Keep this list focused on speakers with clear, natural General
# American English (news anchors, US late-night hosts, dialect coaches, etc).
CURATED_HANDLES: List[Dict[str, str]] = [
    # News / broadcast
    {"handle": "NPR",              "label": "NPR"},
    {"handle": "CBSNews",          "label": "CBS News"},
    {"handle": "PBSNewsHour",      "label": "PBS NewsHour"},
    {"handle": "ABCNews",          "label": "ABC News"},
    {"handle": "CNN",              "label": "CNN"},
    {"handle": "NBCNews",          "label": "NBC News"},
    {"handle": "60minutes",        "label": "60 Minutes"},
    {"handle": "CBSSundayMorning", "label": "CBS Sunday Morning"},
    {"handle": "TODAY",            "label": "TODAY"},
    {"handle": "CNBC",             "label": "CNBC"},
    {"handle": "bloomberglp",      "label": "Bloomberg"},
    # Late-night / talk
    {"handle": "FallonTonight",    "label": "The Tonight Show"},
    {"handle": "TheEllenShow",     "label": "The Ellen Show"},
    {"handle": "TeamCoco",         "label": "Conan O'Brien"},
    {"handle": "JimmyKimmelLive",  "label": "Jimmy Kimmel Live"},
    {"handle": "colbertlateshow",  "label": "The Late Show w/ Colbert"},
    {"handle": "TheDailyShow",     "label": "The Daily Show"},
    {"handle": "LateNightSeth",    "label": "Late Night w/ Seth Meyers"},
    # Interviews / long-form
    {"handle": "FirstWeFeast",     "label": "Hot Ones"},
    {"handle": "VanityFair",       "label": "Vanity Fair"},
    {"handle": "GQ",               "label": "GQ"},
    {"handle": "Variety",          "label": "Variety"},
    {"handle": "Vogue",            "label": "Vogue"},
    {"handle": "Archdigest",       "label": "Architectural Digest"},
    {"handle": "hollywoodreporter", "label": "The Hollywood Reporter"},
    {"handle": "IMDb",             "label": "IMDb"},
    # Educational / long-form
    {"handle": "TED",              "label": "TED"},
    {"handle": "TEDEd",            "label": "TED-Ed"},
    {"handle": "bigthink",         "label": "Big Think"},
    {"handle": "Vox",              "label": "Vox"},
    {"handle": "crashcourse",      "label": "CrashCourse"},
    {"handle": "NatGeo",           "label": "National Geographic"},
    {"handle": "scishow",          "label": "SciShow"},
    {"handle": "veritasium",       "label": "Veritasium"},
    {"handle": "mkbhd",            "label": "MKBHD"},
    {"handle": "MasterClass",      "label": "MasterClass"},
    # Dialect / accent-focused
    {"handle": "WIRED",            "label": "WIRED (Erik Singer)"},
    {"handle": "businessinsider",  "label": "Business Insider"},
    {"handle": "rachelsenglish",   "label": "Rachel's English"},
    {"handle": "MerriamWebster",   "label": "Merriam-Webster"},
    # Movie & entertainment press
    {"handle": "MOVIECLIPS",              "label": "Movieclips"},
    {"handle": "FandangoMovieClips",      "label": "Fandango"},
    {"handle": "RegalMovies",             "label": "Regal Movies"},
    {"handle": "entertainmenttonight",    "label": "Entertainment Tonight"},
    {"handle": "AccessHollywood",         "label": "Access Hollywood"},
    {"handle": "HollywoodLife",           "label": "Hollywood Life"},
    {"handle": "popsugar",                "label": "PopSugar"},
    # Podcast heavy-hitters (YouTube channels)
    {"handle": "lexfridman",              "label": "Lex Fridman"},
    {"handle": "PowerfulJRE",             "label": "Joe Rogan Experience"},
    {"handle": "smartless",               "label": "SmartLess"},
    {"handle": "armchairexpertpodcast",   "label": "Armchair Expert"},
    {"handle": "HowIBuiltThis",           "label": "How I Built This"},
    # Actor / celebrity talk shows (American hosts)
    {"handle": "TheDrewBarrymoreShow",    "label": "The Drew Barrymore Show"},
    {"handle": "KellyClarksonShow",       "label": "The Kelly Clarkson Show"},
    # Sports broadcasters (American)
    {"handle": "espn",                    "label": "ESPN"},
    {"handle": "NFL",                     "label": "NFL"},
    {"handle": "NBA",                     "label": "NBA"},
    {"handle": "mlb",                     "label": "MLB"},
    # Food & cooking (very high captions coverage)
    {"handle": "bonappetit",              "label": "Bon Appétit"},
    {"handle": "BingingWithBabish",       "label": "Babish Culinary Universe"},
    {"handle": "foodnetwork",             "label": "Food Network"},
    {"handle": "americastestkitchen",     "label": "America's Test Kitchen"},
    # Late-night / talk show (extras)
    {"handle": "jimmyfallon",             "label": "Jimmy Fallon (channel)"},
    {"handle": "SNL",                     "label": "Saturday Night Live"},
    # Podcasts / long-form interviews (extras)
    {"handle": "TheTimFerrissShow",       "label": "Tim Ferriss"},
    {"handle": "hubermanlab",             "label": "Huberman Lab"},
    {"handle": "TheDailyPodcast",         "label": "The Daily (NYT)"},
    # Science / education (extras)
    {"handle": "kurzgesagt",              "label": "Kurzgesagt"},
    {"handle": "Vsauce",                  "label": "Vsauce"},
    {"handle": "Numberphile",             "label": "Numberphile"},
    {"handle": "SmarterEveryDay",         "label": "Smarter Every Day"},
    {"handle": "MinutePhysics",           "label": "MinutePhysics"},
    # Tech (American hosts)
    {"handle": "LinusTechTips",           "label": "Linus Tech Tips"},
    {"handle": "TheVerge",                "label": "The Verge"},
    {"handle": "cnet",                    "label": "CNET"},
    # Reactions / commentary (high caption density)
    {"handle": "REACT",                   "label": "REACT (Fine Bros)"},
    {"handle": "Cut",                     "label": "Cut"},
    # History & culture
    {"handle": "HistoryChannel",          "label": "History Channel"},
    {"handle": "SmithsonianChannel",      "label": "Smithsonian Channel"},
    # Music interviews / performances (American voices)
    {"handle": "genius",                  "label": "Genius"},
    {"handle": "npcmusic",                "label": "NPR Music"},
]

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

# Titles matching this pattern are almost always songs / music videos — bad
# examples for pronunciation practice because they're sung, not spoken. We
# filter them out of the fallback pool to keep speech content on top.
MUSIC_TITLE_RE = re.compile(
    r"(?i)(\bofficial\s+(music\s+)?video\b|\blyrics?\b|\bvevo\b|\baudio\b|"
    r"\bfeat\.?\s|\bft\.\s|\bx\s+[A-Z]|\btopic\b|\bremix\b|"
    r"\bmusic\s+video\b|\bnew\s+song\b|\balbum\b|\bsingle\b)"
)


def _is_musicy_title(title: str, channel_title: str = "") -> bool:
    """Heuristic filter to keep music videos out of pronunciation examples."""
    if not title:
        return False
    if MUSIC_TITLE_RE.search(title):
        return True
    # " - Topic" auto-generated music channels
    if channel_title.endswith("- Topic"):
        return True
    return False


@dataclass
class CaptionHit:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    offset_seconds: float
    snippet: str


class CaptionSearchService:
    """Encapsulates YouTube search + caption scanning with Mongo caching."""

    # Cache TTLs (seconds)
    CHANNEL_TTL = 30 * 24 * 3600        # 30 days for channel-id lookups
    RESULT_TTL = 30 * 24 * 3600         # 30 days for successful transcripts
    MISS_TTL = 60 * 60                  # 1 hour for misses/rate-limits (retry later)

    def __init__(self, db):
        self.db = db
        self.api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        # Local in-process channel-id cache to avoid repeated Mongo hits.
        self._channel_ids: Optional[List[str]] = None
        self._channel_meta: Dict[str, Dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Channel allowlist resolution
    # ------------------------------------------------------------------
    async def _resolve_channel(self, handle: str) -> Optional[Dict[str, str]]:
        """Look up a channel id by @handle. Cached in Mongo indefinitely."""
        norm = handle.lower().lstrip("@")
        cached = await self.db.caption_channel_cache.find_one({"handle": norm})
        if cached and cached.get("channel_id"):
            return {
                "channel_id": cached["channel_id"],
                "handle": norm,
                "title": cached.get("title", norm),
            }
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{YOUTUBE_API_BASE}/channels",
                    params={
                        "part": "snippet",
                        "forHandle": f"@{norm}",
                        "key": self.api_key,
                    },
                )
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("channel resolve failed for %s: %s", norm, exc)
            return None
        items = data.get("items") or []
        if not items:
            return None
        item = items[0]
        cid = item.get("id")
        title = (item.get("snippet") or {}).get("title", norm)
        if not cid:
            return None
        await self.db.caption_channel_cache.update_one(
            {"handle": norm},
            {"$set": {"handle": norm, "channel_id": cid, "title": title,
                      "cached_at": time.time()}},
            upsert=True,
        )
        return {"channel_id": cid, "handle": norm, "title": title}

    async def _get_curated_channel_ids(self) -> List[str]:
        """Resolve every curated handle to a channel id, cached long-term."""
        if self._channel_ids is not None:
            return self._channel_ids
        resolved = await asyncio.gather(*[
            self._resolve_channel(h["handle"]) for h in CURATED_HANDLES
        ])
        ids: List[str] = []
        for entry, meta in zip(CURATED_HANDLES, resolved):
            if not meta:
                continue
            ids.append(meta["channel_id"])
            self._channel_meta[meta["channel_id"]] = {
                "handle": meta["handle"],
                "label": entry["label"],
                "title": meta["title"],
            }
        self._channel_ids = ids
        logger.info("Resolved %d/%d curated channels", len(ids), len(CURATED_HANDLES))
        return ids

    # ------------------------------------------------------------------
    # YouTube search
    # ------------------------------------------------------------------
    async def _youtube_search(self, query: str) -> Dict[str, Any]:
        """ONE broad YouTube search (100 quota units) then post-filter to
        curated American-speaker channels.

        Earlier we ran a parallel per-channel search (1000 units/query),
        which burnt the 10K daily quota in ~10 queries. Broad search gives
        us ~100 fresh queries/day; Mongo caching makes repeat words free.

        Returns {"items": [...], "quota_exceeded": bool}.
        """
        if not self.api_key:
            return {"items": [], "quota_exceeded": False}
        channel_ids = await self._get_curated_channel_ids()
        if not channel_ids:
            return {"items": [], "quota_exceeded": False}
        curated = set(channel_ids)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    f"{YOUTUBE_API_BASE}/search",
                    params={
                        "part": "snippet",
                        "q": query,
                        "type": "video",
                        "videoEmbeddable": "true",
                        "regionCode": "US",
                        "relevanceLanguage": "en",
                        "maxResults": 50,       # max allowed; still 100 quota units
                        "safeSearch": "none",
                        "key": self.api_key,
                    },
                )
                if r.status_code in (403, 429):
                    body = r.text or ""
                    is_quota = ("quota" in body.lower()
                                or "rateLimitExceeded" in body
                                or "dailyLimitExceeded" in body)
                    logger.error("YouTube API %s (%s): %s", r.status_code,
                                 "quota" if is_quota else "auth", body[:200])
                    return {"items": [], "quota_exceeded": bool(is_quota)}
                r.raise_for_status()
                combined = (r.json().get("items") or [])

                # Post-filter to curated channels, dedup by video id.
                filtered: List[Dict[str, Any]] = []
                seen: set = set()
                for it in combined:
                    snip = it.get("snippet") or {}
                    cid = snip.get("channelId")
                    vid = (it.get("id") or {}).get("videoId")
                    if not cid or not vid or cid not in curated or vid in seen:
                        continue
                    if _is_musicy_title(snip.get("title", ""),
                                        snip.get("channelTitle", "")):
                        continue
                    seen.add(vid)
                    filtered.append(it)

                # Also collect the non-curated results as a top-up pool so
                # we always have SOMETHING to show. Curated hits are still
                # preferred in ordering (they come first in `filtered`);
                # non-curated results are appended so they only surface
                # when curated + embeddability filtering leaves us short.
                # Music/song titles are dropped from the top-up too.
                topup: List[Dict[str, Any]] = []
                for it in combined:
                    snip = it.get("snippet") or {}
                    cid = snip.get("channelId")
                    vid = (it.get("id") or {}).get("videoId")
                    if not cid or not vid or vid in seen:
                        continue
                    if _is_musicy_title(snip.get("title", ""),
                                        snip.get("channelTitle", "")):
                        continue
                    seen.add(vid)
                    topup.append(it)
                filtered.extend(topup)

                # Confirm embeddability at the video level — the search flag
                # misses some geo/copyright-restricted news clips.
                ids = [f["id"]["videoId"] for f in filtered]
                allowed = await self._check_embeddable(client, ids)
                items = [
                    it for it in filtered
                    if (it.get("id") or {}).get("videoId") in allowed
                ]
                return {"items": items, "quota_exceeded": False}
        except Exception as exc:  # noqa: BLE001
            logger.warning("youtube broad search failed for %r: %s", query, exc)
            return {"items": [], "quota_exceeded": False}

    async def _check_embeddable(
        self,
        client: httpx.AsyncClient,
        video_ids: List[str],
    ) -> set:
        """Batch-check videos.list for embeddable + not-region-blocked-in-US.
        Returns the set of video ids that pass. Cheap: 1 quota / 50 ids."""
        allowed: set = set()
        if not video_ids:
            return allowed
        # YouTube caps videos.list at 50 ids per request.
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            try:
                r = await client.get(
                    f"{YOUTUBE_API_BASE}/videos",
                    params={
                        "part": "status,contentDetails",
                        "id": ",".join(chunk),
                        "key": self.api_key,
                    },
                )
                r.raise_for_status()
                data = r.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("videos.list check failed: %s", exc)
                # Fall back to trusting the search-time filter.
                allowed.update(chunk)
                continue
            for item in data.get("items", []):
                status = item.get("status") or {}
                cd = item.get("contentDetails") or {}
                region = cd.get("regionRestriction") or {}
                blocked = set(region.get("blocked") or [])
                allowed_regions = region.get("allowed")
                us_ok = (
                    "US" not in blocked
                    and (allowed_regions is None or "US" in allowed_regions)
                )
                if status.get("embeddable") and us_ok:
                    allowed.add(item["id"])
        return allowed

    # ------------------------------------------------------------------
    # Caption fetch + scan
    # ------------------------------------------------------------------
    @staticmethod
    def _find_word_in_transcript(
        transcript: List[Dict[str, Any]],
        query: str,
    ) -> Optional[Dict[str, Any]]:
        """Locate the query word inside a transcript. Case-insensitive,
        whole-word match. Returns {offset, snippet} or None."""
        target = query.lower().strip()
        if not target:
            return None
        # Support multi-word queries and single words alike.
        for entry in transcript:
            text = (entry.get("text") or "").strip()
            if not text:
                continue
            words = [w.lower() for w in WORD_RE.findall(text)]
            if not words:
                continue
            if " " in target:
                # phrase match: does the lowered text contain the phrase?
                if target in text.lower():
                    return {
                        "offset": float(entry.get("start", 0) or 0),
                        "snippet": text,
                    }
            else:
                if target in words:
                    return {
                        "offset": float(entry.get("start", 0) or 0),
                        "snippet": text,
                    }
        return None

    def _fetch_transcript_sync(self, video_id: str) -> Optional[List[Dict[str, Any]]]:
        """Blocking transcript fetch via yt-dlp. Downloads subtitles into a
        tempdir so yt-dlp handles the session/headers itself (fetching URLs
        directly frequently 403s because the URLs are session-bound)."""
        import glob
        import shutil
        import tempfile

        url = f"https://www.youtube.com/watch?v={video_id}"
        tmp = tempfile.mkdtemp(prefix=f"yt_{video_id}_")
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en-orig", "en.*"],
            "subtitlesformat": "json3/vtt/best",
            "outtmpl": f"{tmp}/%(id)s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 15,
            "retries": 1,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            },
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("yt-dlp caption fetch failed for %s: %s", video_id, exc)
            shutil.rmtree(tmp, ignore_errors=True)
            return None

        # Pick the best subtitle file: prefer manual en/en-US, then auto.
        files = sorted(glob.glob(f"{tmp}/*.json3")) + sorted(glob.glob(f"{tmp}/*.vtt"))
        if not files:
            shutil.rmtree(tmp, ignore_errors=True)
            return None

        # Prefer manual (no "-orig" and no auto marker) but any works.
        def _score(path: str) -> int:
            lname = path.lower()
            score = 0
            if "en-us" in lname:
                score += 20
            elif ".en." in lname or lname.endswith(".en.json3") or lname.endswith(".en.vtt"):
                score += 15
            if "orig" in lname:
                score -= 5
            if lname.endswith(".json3"):
                score += 2
            return score

        files.sort(key=_score, reverse=True)
        chosen = files[0]
        try:
            with open(chosen, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if chosen.endswith(".json3"):
            return self._parse_json3(raw)
        return self._parse_vtt(raw)

    @staticmethod
    def _parse_json3(raw: str) -> List[Dict[str, Any]]:
        import json
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        events = data.get("events") or []
        out: List[Dict[str, Any]] = []
        for ev in events:
            segs = ev.get("segs") or []
            if not segs:
                continue
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if not text or text == "\n":
                continue
            start_ms = ev.get("tStartMs") or 0
            dur_ms = ev.get("dDurationMs") or 0
            out.append({
                "text": text.replace("\n", " "),
                "start": start_ms / 1000.0,
                "duration": dur_ms / 1000.0,
            })
        return out

    @staticmethod
    def _parse_vtt(raw: str) -> List[Dict[str, Any]]:
        """Minimal WebVTT parser: [start --> end] then one or more text lines."""
        out: List[Dict[str, Any]] = []
        blocks = re.split(r"\n\s*\n", raw)
        ts = re.compile(
            r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*"
            r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})"
        )
        for block in blocks:
            m = ts.search(block)
            if not m:
                continue
            h, mn, s, ms = map(int, m.group(1, 2, 3, 4))
            eh, em, es, ems = map(int, m.group(5, 6, 7, 8))
            start = h * 3600 + mn * 60 + s + ms / 1000.0
            end = eh * 3600 + em * 60 + es + ems / 1000.0
            text_lines = []
            for line in block.splitlines():
                if ts.search(line) or line.strip().startswith(("WEBVTT", "NOTE")):
                    continue
                # Strip inline tags like <c> and timestamp <00:00:01.000> markers.
                cleaned = re.sub(r"<[^>]+>", "", line).strip()
                if cleaned:
                    text_lines.append(cleaned)
            text = " ".join(text_lines).strip()
            if text:
                out.append({"text": text, "start": start, "duration": max(0.0, end - start)})
        return out

    async def _scan_video(self, video_id: str, query: str) -> Optional[Dict[str, Any]]:
        # Check per-video transcript cache first (Mongo, 30d TTL for hits,
        # 1h TTL for misses so we eventually retry after rate-limits clear).
        cached = await self.db.caption_transcript_cache.find_one({"video_id": video_id})
        if cached and cached.get("expires_at", 0) > time.time():
            transcript = cached.get("transcript")
        else:
            transcript = await asyncio.to_thread(self._fetch_transcript_sync, video_id)
            ttl = self.RESULT_TTL if transcript else self.MISS_TTL
            await self.db.caption_transcript_cache.update_one(
                {"video_id": video_id},
                {"$set": {
                    "video_id": video_id,
                    "transcript": transcript or [],
                    "full_text": self._flatten_transcript(transcript or []),
                    "has_transcript": bool(transcript),
                    "expires_at": time.time() + ttl,
                    "cached_at": time.time(),
                }},
                upsert=True,
            )
            # Small delay between live fetches to avoid YouTube rate-limits.
            await asyncio.sleep(1.5)
        if not transcript:
            return None
        return self._find_word_in_transcript(transcript, query)

    @staticmethod
    def _flatten_transcript(transcript: List[Dict[str, Any]]) -> str:
        """Join a transcript's caption chunks into one plain-text blob so
        Mongo's text index can search across it."""
        parts: List[str] = []
        for entry in transcript or []:
            text = entry.get("text") or ""
            if text:
                parts.append(text)
        return " ".join(parts)

    async def search_local_transcripts(
        self, query: str, limit: int = 6
    ) -> List[Dict[str, Any]]:
        """Query our own Mongo transcript index for videos whose captions
        contain the word/phrase. Instant, offline of YouTube's API.

        Falls back to nothing if no matches — caller decides whether to
        run the live YouTube search next.
        """
        query = (query or "").strip()
        if not query:
            return []
        # Mongo text search on full_text. Requires a text index on the
        # caption_transcript_cache.full_text field (see ensure_indexes).
        # Also self-heal: score-sort by textScore for best matches.
        cursor = self.db.caption_transcript_cache.find(
            {"$text": {"$search": f'"{query}"'},
             "has_transcript": True},
            {"_id": 0, "score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(limit * 3)
        results: List[Dict[str, Any]] = []
        target = query.lower()
        target_words = WORD_RE.findall(target)
        async for doc in cursor:
            hit = self._find_word_in_transcript(
                doc.get("transcript") or [], query
            )
            if not hit:
                continue
            meta = doc.get("channel_meta") or {}
            results.append({
                "video_id": doc["video_id"],
                "title": meta.get("title") or doc.get("title") or "",
                "channel_id": meta.get("channel_id") or doc.get("channel_id") or "",
                "channel_title": meta.get("channel_title") or doc.get("channel_title") or "",
                "thumbnail": meta.get("thumbnail", ""),
                "offset_seconds": max(0.0, float(hit["offset"])),
                "snippet": hit["snippet"],
                "youtube_url": (
                    f"https://www.youtube.com/watch?v={doc['video_id']}"
                    f"&t={int(hit['offset'])}s"
                ),
                "has_timestamp": True,
                "source": "local_index",
            })
            if len(results) >= limit:
                break
        # Silence lint on unused variable (kept for future scoring).
        _ = target_words
        return results

    async def ingest_channel_videos(
        self, channel_id: str, per_channel_limit: int = 50
    ) -> Dict[str, int]:
        """Fetch recent uploads for one channel and cache their transcripts
        into caption_transcript_cache. Idempotent — skips videos we already
        have a fresh transcript for.

        Returns {"ingested": N, "skipped": M, "failed": K}.
        """
        if not self.api_key:
            return {"ingested": 0, "skipped": 0, "failed": 0,
                    "error": "no_api_key"}
        # Uploads playlist id = channel_id with 'UC' → 'UU'
        uploads_id = "UU" + channel_id[2:] if channel_id.startswith("UC") else None
        if not uploads_id:
            return {"ingested": 0, "skipped": 0, "failed": 0,
                    "error": "bad_channel_id"}

        # Enumerate videos in the uploads playlist. Uses 1 quota unit per
        # request × up to 5 pages of 50 = ~5 quota units per channel.
        video_ids: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                while len(video_ids) < per_channel_limit:
                    params = {
                        "part": "snippet,contentDetails",
                        "playlistId": uploads_id,
                        "maxResults": min(50, per_channel_limit - len(video_ids)),
                        "key": self.api_key,
                    }
                    if page_token:
                        params["pageToken"] = page_token
                    r = await client.get(
                        f"{YOUTUBE_API_BASE}/playlistItems", params=params
                    )
                    if r.status_code in (403, 429):
                        return {"ingested": 0, "skipped": 0, "failed": 0,
                                "error": "quota_or_auth"}
                    r.raise_for_status()
                    data = r.json()
                    for it in data.get("items", []):
                        snip = it.get("snippet") or {}
                        cd = it.get("contentDetails") or {}
                        vid = cd.get("videoId")
                        if not vid:
                            continue
                        video_ids.append({
                            "video_id": vid,
                            "title": snip.get("title", ""),
                            "channel_id": channel_id,
                            "channel_title": snip.get("channelTitle", ""),
                            "thumbnail": (snip.get("thumbnails", {})
                                          .get("medium") or {}).get("url", ""),
                        })
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
        except Exception as exc:  # noqa: BLE001
            logger.warning("ingest playlist failed for %s: %s", channel_id, exc)
            return {"ingested": 0, "skipped": 0, "failed": 0,
                    "error": str(exc)[:200]}

        # For each video, check cache; if stale/missing, fetch + store.
        ingested = 0
        skipped = 0
        failed = 0
        for meta in video_ids:
            existing = await self.db.caption_transcript_cache.find_one(
                {"video_id": meta["video_id"]}, {"expires_at": 1, "_id": 0}
            )
            if existing and existing.get("expires_at", 0) > time.time():
                skipped += 1
                continue
            transcript = await asyncio.to_thread(
                self._fetch_transcript_sync, meta["video_id"]
            )
            has_t = bool(transcript)
            ttl = self.RESULT_TTL if has_t else self.MISS_TTL
            await self.db.caption_transcript_cache.update_one(
                {"video_id": meta["video_id"]},
                {"$set": {
                    "video_id": meta["video_id"],
                    "transcript": transcript or [],
                    "full_text": self._flatten_transcript(transcript or []),
                    "has_transcript": has_t,
                    "channel_meta": meta,  # persist title/channel for search hits
                    "expires_at": time.time() + ttl,
                    "cached_at": time.time(),
                }},
                upsert=True,
            )
            if has_t:
                ingested += 1
            else:
                failed += 1
            # Be gentle on the transcript endpoint.
            await asyncio.sleep(1.2)
        return {"ingested": ingested, "skipped": skipped, "failed": failed}

    async def ensure_local_indexes(self) -> None:
        """Create the Mongo text index on caption transcripts. Idempotent."""
        try:
            await self.db.caption_transcript_cache.create_index(
                [("full_text", "text")], default_language="english",
                name="caption_fulltext",
            )
        except Exception as exc:
            logger.warning("caption text index create failed: %s", exc)

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        limit: int = 6,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"query": query, "results": [], "cached": False}
        if not self.api_key:
            return {
                "query": query,
                "results": [],
                "cached": False,
                "error": "YouTube API key not configured on the server.",
            }

        cache_key = query.lower()
        if not force_refresh:
            cached = await self.db.caption_search_cache.find_one({"query": cache_key})
            if cached and cached.get("expires_at", 0) > time.time():
                return {
                    "query": query,
                    "results": cached.get("results", []),
                    "cached": True,
                }

        # PATH 1 — local transcript index (instant). Only when we already
        # have enough curated-channel videos ingested for this term.
        local_hits = await self.search_local_transcripts(query, limit=limit)
        if len(local_hits) >= limit:
            await self.db.caption_search_cache.update_one(
                {"query": cache_key},
                {"$set": {
                    "query": cache_key,
                    "results": local_hits,
                    "expires_at": time.time() + self.RESULT_TTL,
                    "cached_at": time.time(),
                }},
                upsert=True,
            )
            return {
                "query": query,
                "results": local_hits,
                "cached": False,
                "source": "local_index",
            }

        # PATH 2 — live YouTube search (existing flow). Merge with any
        # partial local hits at the top so we never regress result count.
        curated_ids = set(await self._get_curated_channel_ids())
        search_data = await self._youtube_search(query)
        items = search_data["items"]
        quota_exceeded = search_data["quota_exceeded"]

        # _youtube_search already applied the curated allowlist (with an
        # unfiltered fallback when curated returns nothing). Here we just
        # dedupe by video id and shape the payload.
        candidates: List[Dict[str, str]] = []
        seen_vids = set()
        for it in items:
            snip = it.get("snippet") or {}
            cid = snip.get("channelId")
            vid_obj = it.get("id") or {}
            vid = vid_obj.get("videoId") if isinstance(vid_obj, dict) else None
            if not cid or not vid or vid in seen_vids:
                continue
            seen_vids.add(vid)
            candidates.append({
                "video_id": vid,
                "title": snip.get("title", ""),
                "channel_id": cid,
                "channel_title": snip.get("channelTitle", ""),
                "thumbnail": (snip.get("thumbnails", {}).get("medium") or {}).get("url", ""),
            })

        # Scan captions with limited parallelism. YouTube's transcript
        # endpoint tolerates small bursts; 4 concurrent scans get us the
        # first hits ~4× faster than serial while staying well under
        # per-IP rate ceilings. Once a transcript is cached in Mongo,
        # subsequent scans of the same video are instant.
        results: List[Dict[str, Any]] = []
        sem = asyncio.Semaphore(4)

        async def _scan(cand: Dict[str, str]):
            async with sem:
                hit = await self._scan_video(cand["video_id"], query)
                if not hit:
                    return None
                seconds = max(0.0, float(hit["offset"]))
                return {
                    **cand,
                    "offset_seconds": seconds,
                    "snippet": hit["snippet"],
                    "youtube_url": f"https://www.youtube.com/watch?v={cand['video_id']}&t={int(seconds)}s",
                }

        # Fire scans until we've collected `limit` matches, or overall
        # timeout, whichever first. Cap at 8 candidates to keep total
        # per-query transcript fetches predictable.
        pending = [asyncio.create_task(_scan(c)) for c in candidates[:8]]
        precise: List[Dict[str, Any]] = []
        fallback_pool: List[Dict[str, Any]] = list(candidates[:limit])
        SCAN_BUDGET_SECONDS = 4.0
        deadline = asyncio.get_event_loop().time() + SCAN_BUDGET_SECONDS
        try:
            while pending and len(precise) < limit:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                done, pending_set = await asyncio.wait(
                    pending,
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    break  # hit the budget
                pending = list(pending_set)
                for t in done:
                    try:
                        res = t.result()
                    except Exception:
                        res = None
                    if res:
                        precise.append(res)
                        if len(precise) >= limit:
                            break
        finally:
            for t in pending:
                if not t.done():
                    t.cancel()

        # Build final results: local index hits first (they're guaranteed
        # to be curated + word-in-caption), then live-search precise
        # (timestamped) hits, then untimestamped fallbacks.
        results: List[Dict[str, Any]] = []
        seen_result_ids: set = set()
        for h in local_hits:
            if h["video_id"] in seen_result_ids:
                continue
            seen_result_ids.add(h["video_id"])
            results.append(h)
        for p in precise:
            if p["video_id"] in seen_result_ids:
                continue
            seen_result_ids.add(p["video_id"])
            results.append(p)
        if len(results) < limit:
            for cand in fallback_pool:
                if cand["video_id"] in seen_result_ids:
                    continue
                seen_result_ids.add(cand["video_id"])
                results.append({
                    **cand,
                    "offset_seconds": 0.0,
                    "snippet": "",
                    "has_timestamp": False,
                    "youtube_url": f"https://www.youtube.com/watch?v={cand['video_id']}",
                })
                if len(results) >= limit:
                    break
        results = results[:limit]

        # Mark precise entries too so the client can style differently.
        for r in results:
            r.setdefault("has_timestamp", bool(r.get("snippet")))

        # Sort: precise hits first (earliest offset first), then fallbacks.
        results.sort(key=lambda r: (0 if r["has_timestamp"] else 1,
                                    r["offset_seconds"]))

        # Cache the top-level query. Successful queries get the long TTL;
        # empty results only get MISS_TTL so we retry after rate-limits pass
        # rather than showing an empty state for 30 days.
        top_ttl = self.RESULT_TTL if results else self.MISS_TTL
        await self.db.caption_search_cache.update_one(
            {"query": cache_key},
            {"$set": {
                "query": cache_key,
                "results": results,
                "expires_at": time.time() + top_ttl,
                "cached_at": time.time(),
            }},
            upsert=True,
        )
        response: Dict[str, Any] = {
            "query": query,
            "results": results,
            "cached": False,
        }
        if not results and quota_exceeded:
            response["error"] = (
                "YouTube daily search quota exceeded on the server. "
                "Fresh searches will resume after midnight Pacific time; "
                "words you've already searched today remain available."
            )
        return response
