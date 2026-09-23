"""Slur screen for Real Speakers clips: a video whose captions contain a
slur anywhere is excluded outright. Ordinary swearing is allowed (actors
need it). The word list is editable in Admin (stored in `settings`)."""
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_WORDS: List[str] = [
    "nigga", "niggah", "nigger", "nigguh", "faggot", "fag", "kike", "spic", "spick",
    "wetback", "gook", "tranny", "trannies", "retard", "retarded", "chink",
    "towelhead", "raghead", "beaner", "paki", "jigaboo", "darkie", "zipperhead",
]

_words: List[str] = list(DEFAULT_WORDS)
SLUR_RE: re.Pattern = re.compile(r"(?!x)x")  # never matches until built


def _build(words: List[str]) -> re.Pattern:
    alts = [re.escape(w.lower()) + "s?" for w in words if w.strip()]
    if not alts:
        return re.compile(r"(?!x)x")
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b", re.IGNORECASE)


def set_words(words: List[str]) -> List[str]:
    global _words, SLUR_RE
    clean, seen = [], set()
    for w in words:
        w = re.sub(r"[^a-z' -]", "", (w or "").strip().lower())
        if w and w not in seen:
            seen.add(w)
            clean.append(w)
    _words = clean
    SLUR_RE = _build(clean)
    return clean


def words() -> List[str]:
    return list(_words)


set_words(DEFAULT_WORDS)


async def load(db) -> List[str]:
    """Load the admin-edited list from Mongo (seeding defaults on first run)."""
    doc = await db.settings.find_one({"key": "blocked_words"}, {"_id": 0, "words": 1})
    if doc is None:
        await db.settings.update_one({"key": "blocked_words"},
                                     {"$set": {"words": DEFAULT_WORDS}}, upsert=True)
        return set_words(DEFAULT_WORDS)
    return set_words(doc.get("words") or [])


async def save(db, new_words: List[str]) -> List[str]:
    clean = set_words(new_words)
    await db.settings.update_one({"key": "blocked_words"}, {"$set": {"words": clean}}, upsert=True)
    return clean


def has_slur(transcript: Optional[List[Dict[str, Any]]]) -> bool:
    return any(SLUR_RE.search(e.get("text") or "") for e in transcript or [])
