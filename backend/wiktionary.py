"""General American IPA from Wiktionary (free), for words CMU doesn't know.

Parses the English section's Pronunciation lines and prefers entries tagged
GA / US / GenAm. Results are cached in Mongo (`ipa_lookup_cache`).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Dict, Iterable, List, Optional

import httpx

logger = logging.getLogger(__name__)

API = "https://en.wiktionary.org/w/api.php"
HEADERS = {"User-Agent": "PronounceIt/1.0 (accent coaching app; contact info@katherinebeck.com)"}
TTL_HIT = 180 * 24 * 3600
TTL_MISS = 7 * 24 * 3600

_IPA_TPL = re.compile(r"\{\{IPA\|en\|([^}]*)\}\}")
_US_TAGS = re.compile(r"\b(GA|GenAm|US|American|General American)\b", re.I)


def _english_section(wikitext: str) -> str:
    m = re.search(r"^==\s*English\s*==\s*$(.*?)(?=^==[^=]|\Z)", wikitext, re.S | re.M)
    return m.group(1) if m else ""


def parse_ga_ipa(wikitext: str) -> Optional[str]:
    section = _english_section(wikitext)
    if not section:
        return None
    candidates: List[tuple] = []
    parent = ""   # accent context from the enclosing "* {{a|US}}" bullet
    for line in section.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("*") and not stripped.startswith("**"):
            parent = line
        if "{{IPA|en|" not in line:
            continue
        for tpl in _IPA_TPL.finditer(line):
            parts = [p for p in tpl.group(1).split("|")]
            transcriptions = [p for p in parts if p.startswith(("/", "["))]
            if not transcriptions:
                continue
            tags = " ".join(p for p in parts if "=" in p) + " " + line + " " + parent
            us = bool(_US_TAGS.search(tags))
            for t in transcriptions:
                ipa = t.strip("/[]").replace(".", "")
                british = ("ː" in ipa) or ("ɒ" in ipa)
                # Prefer US-tagged, non-British-looking, stressed citation forms.
                candidates.append((0 if us else 1, 1 if british else 0,
                                   0 if "ˈ" in ipa else 1, ipa))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[:3])
    return candidates[0][3] or None


class WiktionaryIPA:
    def __init__(self, db):
        self.db = db

    async def _fetch_wikitext(self, client: httpx.AsyncClient, title: str) -> Optional[str]:
        r = await client.get(API, params={
            "action": "parse", "page": title, "prop": "wikitext",
            "format": "json", "formatversion": 2, "redirects": 1,
        }, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        return (r.json().get("parse") or {}).get("wikitext")

    async def lookup(self, word: str) -> Optional[str]:
        key = word.strip().lower()
        if not key or self.db is None:
            return None
        cached = await self.db.ipa_lookup_cache.find_one({"word": key})
        if cached and cached.get("expires_at", 0) > time.time():
            return cached.get("ipa")
        ipa: Optional[str] = None
        try:
            async with httpx.AsyncClient() as client:
                for title in dict.fromkeys([word.strip(), key, key.capitalize()]):
                    text = await self._fetch_wikitext(client, title)
                    if text:
                        ipa = parse_ga_ipa(text)
                        if ipa:
                            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiktionary lookup failed for %r: %s", word, exc)
            return None
        await self.db.ipa_lookup_cache.update_one(
            {"word": key},
            {"$set": {"word": key, "ipa": ipa, "source": "wiktionary",
                      "expires_at": time.time() + (TTL_HIT if ipa else TTL_MISS)}},
            upsert=True,
        )
        return ipa

    async def lookup_many(self, words: Iterable[str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for w in words:
            ipa = await self.lookup(w)
            if ipa:
                out[w.lower()] = ipa
        return out
