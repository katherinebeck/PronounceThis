"""Accent guard — non-US slang/dialect words that Eleven v4 tends to voice in their
home accent (strewth → Australian). Listed words are always rendered with their
General American IPA (scene lines + Word tool) via phonetics.CUSTOM_IPA, unless the
coach already has her own My Dictionary entry for the word (hers wins).
"""
import re
from typing import Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from phonetics import CUSTOM_IPA, arpabet_to_ipa, get_arpabet

KEY = "accent_guard"

# word → GA IPA (None = take CMU). Australian / British / Irish / NZ / South African.
DEFAULTS: Dict[str, Optional[str]] = {
    "strewth": "stɹuθ", "crikey": "ˈkɹaɪki", "arvo": "ˈɑɹvoʊ", "brekkie": "ˈbɹɛki", "g'day": "ɡəˈdeɪ",
    "bogan": "ˈboʊɡən", "dunny": "ˈdʌni", "servo": "ˈsɝvoʊ", "bottle-o": "ˈbɑɾəloʊ", "tradie": "ˈtɹeɪdi",
    "ute": "jut", "esky": "ˈɛski", "thongs": None, "fair dinkum": "fɛɹ ˈdɪŋkəm", "sheila": "ˈʃilə",
    "bloke": "bloʊk", "mate": None, "reckon": None, "heaps": None, "chook": "tʃʊk", "footy": "ˈfʊɾi",
    "maccas": "ˈmækəz", "sunnies": "ˈsʌniz", "rellies": "ˈɹɛliz", "ripper": None, "stoked": None,
    "blimey": "ˈblaɪmi", "bloody": None, "bollocks": "ˈbɑləks", "knackered": "ˈnækɚd", "gobsmacked": "ˈɡɑbˌsmækt",
    "chuffed": "tʃʌft", "wanker": "ˈwæŋkɚ", "bugger": "ˈbʌɡɚ", "bloke's": "bloʊks", "cheers": None, "mental": None,
    "dodgy": "ˈdɑdʒi", "gutted": "ˈɡʌɾɪd", "skint": "skɪnt", "quid": "kwɪd", "loo": "lu", "telly": "ˈtɛli",
    "brolly": "ˈbɹɑli", "fag": None, "fortnight": None, "wee": None, "lass": None, "lad": None, "bairn": "bɛɹn",
    "innit": "ˈɪnɪt", "cuppa": "ˈkʌpə", "kerfuffle": "kɚˈfʌfəl", "shambles": None, "whinge": "wɪndʒ", "gormless": "ˈɡɔɹmləs",
    "eejit": "ˈidʒɪt", "craic": "kɹæk", "feck": "fɛk", "grand": None, "banjaxed": "ˈbændʒækst", "gobshite": "ˈɡɑbʃaɪt",
    "lekker": "ˈlɛkɚ", "bru": "bɹu", "braai": "bɹaɪ", "jol": "dʒɑl", "howzit": "ˈhaʊzɪt", "eish": "eɪʃ",
    "chur": "tʃɝ", "jandals": "ˈdʒændəlz", "bach": "bætʃ", "tramping": None, "sweet as": "swit æz",
}


def _clean(w: str) -> str:
    return re.sub(r"\s+", " ", w.strip().lower())


def _ipa_for(word: str, ipa: Optional[str]) -> Optional[str]:
    if ipa:
        return ipa
    phones = get_arpabet(word)
    return arpabet_to_ipa(phones) if phones else None


async def _coach_words(db: AsyncIOMotorDatabase) -> set:
    return {e["word"] async for e in db.dictionary_entries.find({"ipa_custom": True}, {"_id": 0, "word": 1})}


async def load(db: AsyncIOMotorDatabase) -> List[dict]:
    """Seed defaults once, then push every guard word into CUSTOM_IPA (coach entries win)."""
    doc = await db.settings.find_one({"key": KEY}, {"_id": 0})
    if not doc:
        entries = [{"word": w, "ipa": _ipa_for(w, ipa)} for w, ipa in DEFAULTS.items()]
        entries = [e for e in entries if e["ipa"]]
        await db.settings.update_one({"key": KEY}, {"$set": {"entries": entries}}, upsert=True)
    else:
        entries = doc.get("entries", [])
    coach = await _coach_words(db)
    for e in entries:
        if e["word"] not in coach:
            CUSTOM_IPA[e["word"]] = e["ipa"]
    return entries


async def entries(db: AsyncIOMotorDatabase) -> List[dict]:
    doc = await db.settings.find_one({"key": KEY}, {"_id": 0})
    return sorted((doc or {}).get("entries", []), key=lambda e: e["word"])


async def add(db: AsyncIOMotorDatabase, word: str, ipa: Optional[str]) -> dict:
    w = _clean(word)
    resolved = _ipa_for(w, (ipa or "").strip() or None)
    if not w or not resolved:
        raise ValueError("ipa_required")
    cur = [e for e in await entries(db) if e["word"] != w]
    cur.append({"word": w, "ipa": resolved})
    await db.settings.update_one({"key": KEY}, {"$set": {"entries": cur}}, upsert=True)
    if w not in await _coach_words(db):
        CUSTOM_IPA[w] = resolved
    await _invalidate(db, w)
    return {"word": w, "ipa": resolved}


async def remove(db: AsyncIOMotorDatabase, word: str) -> None:
    w = _clean(word)
    cur = [e for e in await entries(db) if e["word"] != w]
    await db.settings.update_one({"key": KEY}, {"$set": {"entries": cur}}, upsert=True)
    if w not in await _coach_words(db):
        CUSTOM_IPA.pop(w, None)
    await _invalidate(db, w)


async def _invalidate(db: AsyncIOMotorDatabase, w: str) -> None:
    """Cached renders containing the word must re-render with/without the forced IPA."""
    await db.turn_audio_cache.delete_many({"text": {"$regex": rf"\b{re.escape(w)}\b", "$options": "i"}})
    await db.audio_cache.delete_many({"word": {"$in": [w, f"{w}#ph"]}, "manual_override": {"$ne": True}})
