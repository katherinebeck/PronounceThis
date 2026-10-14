"""Admin "My Dictionary": the coach walks the CMU word list alphabetically,
records each word and confirms/edits its IPA. Saved entries drive display
(CUSTOM_IPA) and playback (audio_cache manual overrides)."""
from __future__ import annotations

import base64
import csv
import asyncio
import io
import os
import re
from pathlib import Path
import zipfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from auth import require_admin
from phonetics import (CUSTOM_IPA, PREFERRED_ARPA, classify_ipa, cmu_ipa, cmu_word_list,
                       cmu_words_by_frequency, ipa_to_arpabet)

# Jessica — the voice members hear for single words (mirrors server.DEFAULT_VOICE_ID).
WORD_VOICE_ID = "lxYfHSkYm1EzQzGhdbfc"


def revoice_recording(raw: bytes, voice_id: str = WORD_VOICE_ID) -> bytes:
    """Blocking ElevenLabs speech-to-speech: the coach's take, in the app voice,
    pronunciation and stress preserved."""
    from elevenlabs.client import ElevenLabs
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")
    client = ElevenLabs(api_key=api_key)
    out = b"".join(client.speech_to_speech.convert(
        voice_id=voice_id,
        audio=io.BytesIO(raw),
        model_id="eleven_multilingual_sts_v2",
        output_format="mp3_44100_128",
        remove_background_noise=True,
    ))
    if not out:
        raise RuntimeError("empty speech-to-speech result")
    return out

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
                       "audio/webm", "audio/ogg", "audio/mp4", "audio/m4a"}
MAX_AUDIO_BYTES = 2 * 1024 * 1024
_EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/m4a": "m4a"}
IPA_ALLOWED = re.compile(r"^[a-zɑæɐɛəɜɝɚɪiɔoʊuʌʔbdðfɡghjklɫmnŋpɹrsʃtθvwzʒɾ\u0329\u0303ˈˌː·.\s]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_word(w: str) -> str:
    """Lower-case letters/apostrophes; a single space is kept so place names
    like "baton rouge" can carry their own pronunciation."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z' ]", "", (w or "").lower())).strip()


class WordBody(BaseModel):
    word: str


# American place names whose local pronunciation differs from the dictionary
# reading of the same spelling (toponyms). Phrases carry one IPA piece per
# word so scene tokens can be corrected individually.
TOPONYMS = {
    "baton rouge": "ˌbæt·ən ˈɹuʒ",
    "houston street": "ˈhaʊ·stən stɹit",
    "louisville": "ˈlu·ə·vəl",
    "cairo illinois": "ˈkeɪ·ɹoʊ ˌɪl·əˈnɔɪ",
    "nevada": "nəˈvæd·ə",
    "versailles kentucky": "vɚˈseɪlz kənˈtʌk·i",
    "des moines": "də ˈmɔɪn",
    "reading pennsylvania": "ˈɹɛd·ɪŋ ˌpɛn·səlˈveɪn·jə",
    "new orleans": "nu ˈɔɹ·lənz",
    "appalachia": "ˌæp·əˈlætʃ·ə",
    "boise": "ˈbɔɪ·si",
    "lima ohio": "ˈlaɪ·mə oʊˈhaɪ·oʊ",
}


async def seed_toponyms(db: AsyncIOMotorDatabase) -> int:
    """One-time: add the toponym list as coach dictionary entries, never
    overwriting a word the coach has already entered herself."""
    if await db.app_migrations.find_one({"_id": "toponyms_v1"}):
        return 0
    added = 0
    for w, ipa in TOPONYMS.items():
        if await db.dictionary_entries.find_one({"word": w}, {"_id": 1}):
            continue
        phones = ipa_to_arpabet(ipa) or []
        doc = {"word": w, "ipa": ipa, "cmu_ipa": cmu_ipa(w), "ipa_custom": True,
               "categories": classify_ipa(ipa), "status": "done", "source": "toponyms_v1",
               "arpabet": " ".join(phones), "updated_at": _now_iso()}
        await db.dictionary_entries.update_one({"word": w}, {"$set": doc}, upsert=True)
        CUSTOM_IPA[w] = ipa
        if " " not in w and phones:
            await db.pronunciation_prefs.update_one(
                {"word": w}, {"$set": {"word": w, "arpabet": doc["arpabet"], "ipa": ipa,
                                       "categories": doc["categories"], "source": "dictionary",
                                       "updated_at": _now_iso()}}, upsert=True)
            PREFERRED_ARPA[w] = doc["arpabet"]
        await db.audio_cache.delete_many({"word": {"$in": [w, f"{w}#ph"]}, "manual_override": {"$ne": True}})
        added += 1
    await db.app_migrations.insert_one({"_id": "toponyms_v1", "added": added, "at": _now_iso()})
    return added


async def load_custom_ipa(db: AsyncIOMotorDatabase) -> None:
    async for e in db.dictionary_entries.find({"ipa_custom": True}, {"_id": 0, "word": 1, "ipa": 1}):
        CUSTOM_IPA[e["word"]] = e["ipa"]
    # Recordings made before the dictionary existed become entries too.
    async for a in db.audio_cache.find({"manual_override": True}, {"_id": 0, "word": 1, "content_type": 1}):
        w = a["word"]
        if "#" in w or " " in w:
            continue
        await db.dictionary_entries.update_one(
            {"word": w},
            {"$setOnInsert": {"word": w, "ipa": cmu_ipa(w), "cmu_ipa": cmu_ipa(w), "ipa_custom": False,
                              "has_audio": True, "content_type": a.get("content_type"),
                              "status": "done", "updated_at": _now_iso()}},
            upsert=True)
    await db.dictionary_entries.create_index("word", unique=True)
    await db.dictionary_entries.create_index("status")


# --- Curated word lists (names, places, brands) -----------------------------
_LISTS_DIR = Path(__file__).parent / "data" / "wordlists"
LIST_FILES = {"names": "first_names.txt", "surnames": "surnames.txt", "places": "us_places.txt",
              "countries": "countries.txt", "chains": "chains.txt"}
_LIST_CACHE: dict = {}


def curated_list(name: str) -> list:
    """[(token, label)] in list order; multi-word labels are split into the
    single tokens the dictionary actually stores (e.g. 'Los Angeles' → los, angeles)."""
    if name in _LIST_CACHE:
        return _LIST_CACHE[name]
    out, seen = [], set()
    path = _LISTS_DIR / LIST_FILES[name]
    for label in path.read_text().splitlines():
        label = label.strip()
        if not label:
            continue
        for tok in re.split(r"[\s,()./]+", label):
            w = _clean_word(tok)
            if len(w) > 1 and w not in seen and w not in ("dc",):
                seen.add(w)
                out.append((w, label))
    _LIST_CACHE[name] = out
    return out


def create_dictionary_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(prefix="/admin/dictionary", tags=["dictionary"])

    AUDIO_KEYS = lambda w: [w, f"{w}#ph", f"{w}#human"]  # noqa: E731

    async def _snapshot(w: str) -> None:
        """Save the word's current state so the coach can undo the next save."""
        snap = {
            "word": w, "created_at": _now_iso(),
            "entry": await db.dictionary_entries.find_one({"word": w}, {"_id": 0}),
            "pref": await db.pronunciation_prefs.find_one({"word": w}, {"_id": 0}),
            "audio": await db.audio_cache.find({"word": {"$in": AUDIO_KEYS(w)}}, {"_id": 0}).to_list(10),
        }
        await db.dictionary_history.insert_one(snap)
        old = await db.dictionary_history.find({}, {"_id": 1}).sort("created_at", -1).skip(30).to_list(1000)
        if old:
            await db.dictionary_history.delete_many({"_id": {"$in": [o["_id"] for o in old]}})

    async def _stats(list_name: str = "dictionary") -> dict:
        if list_name in LIST_FILES:
            toks = [w for w, _ in curated_list(list_name)]
            done = await db.dictionary_entries.count_documents({"word": {"$in": toks}, "status": "done"})
            recorded = await db.dictionary_entries.count_documents({"word": {"$in": toks}, "status": "done", "has_audio": True})
            skipped = await db.dictionary_entries.count_documents({"word": {"$in": toks}, "status": "skipped"})
            return {"total": len(toks), "done": done, "recorded": recorded, "skipped": skipped}
        done = await db.dictionary_entries.count_documents({"status": "done"})
        recorded = await db.dictionary_entries.count_documents({"status": "done", "has_audio": True})
        skipped = await db.dictionary_entries.count_documents({"status": "skipped"})
        return {"total": len(cmu_word_list()), "done": done, "recorded": recorded, "skipped": skipped}

    async def _entry(word: str) -> dict:
        e = await db.dictionary_entries.find_one({"word": word}, {"_id": 0}) or {}
        ipa = e.get("ipa") if e.get("ipa_custom") else (cmu_ipa(word) or e.get("ipa"))
        return {"word": word, "ipa": ipa, "cmu_ipa": cmu_ipa(word),
                "ipa_custom": bool(e.get("ipa_custom")), "has_audio": bool(e.get("has_audio")),
                "status": e.get("status"), "in_cmu": bool(cmu_ipa(word))}

    @router.get("/queue")
    async def queue(request: Request, start: Optional[str] = None, limit: int = 12,
                    list: str = "dictionary", include_start: bool = False):
        await require_admin(request, db)
        labels: dict = {}
        if list in LIST_FILES:
            pairs = curated_list(list)
            words = [w for w, _ in pairs]
            labels = dict(pairs)
        else:
            list = "dictionary"
            words = cmu_words_by_frequency()
        pos = 0
        out: list = []
        if start:
            sw = _clean_word(start)
            try:
                pos = words.index(sw)
            except ValueError:
                # Not in this list (a name, "oner"…): put it first so the coach
                # can give it an IPA and/or a take; the queue follows.
                if sw:
                    e = await db.dictionary_entries.find_one({"word": sw}, {"_id": 0, "ipa": 1})
                    out.append({"word": sw, "ipa": (e or {}).get("ipa") or cmu_ipa(sw) or "", "custom": True})
            else:
                if include_start:  # "Back": revisit a word even if already done
                    e = await db.dictionary_entries.find_one({"word": sw}, {"_id": 0, "ipa": 1, "ipa_custom": 1})
                    ipa = e["ipa"] if e and e.get("ipa_custom") else cmu_ipa(sw)
                    out.append({"word": sw, "ipa": ipa or "", "label": labels.get(sw)})
                    pos += 1
        limit = max(1, min(limit, 50))
        while pos < len(words) and len(out) < limit:
            chunk = words[pos:pos + 400]
            pos += len(chunk)
            handled = {e["word"] async for e in db.dictionary_entries.find(
                {"word": {"$in": chunk}, "status": {"$in": ["done", "skipped"]}}, {"_id": 0, "word": 1})}
            for w in chunk:
                if w not in handled:
                    out.append({"word": w, "ipa": cmu_ipa(w) or "", "label": labels.get(w)})
                    if len(out) >= limit:
                        break
        return {"words": out, "stats": await _stats(list), "list": list}

    @router.post("/undo")
    async def undo(request: Request):
        """Revert the most recent save (entry, phoneme pref and audio)."""
        await require_admin(request, db)
        snap = await db.dictionary_history.find_one({}, sort=[("created_at", -1)])
        if not snap:
            raise HTTPException(status_code=404, detail="nothing_to_undo")
        w = snap["word"]
        await db.dictionary_entries.delete_one({"word": w})
        if snap.get("entry"):
            await db.dictionary_entries.insert_one(snap["entry"])
        await db.pronunciation_prefs.delete_one({"word": w})
        if snap.get("pref"):
            await db.pronunciation_prefs.insert_one(snap["pref"])
            PREFERRED_ARPA[w] = snap["pref"].get("arpabet")
        else:
            PREFERRED_ARPA.pop(w, None)
        await db.audio_cache.delete_many({"word": {"$in": AUDIO_KEYS(w)}})
        if snap.get("audio"):
            await db.audio_cache.insert_many(snap["audio"])
        if snap.get("entry") and snap["entry"].get("ipa_custom"):
            CUSTOM_IPA[w] = snap["entry"]["ipa"]
        else:
            CUSTOM_IPA.pop(w, None)
        await db.dictionary_history.delete_one({"_id": snap["_id"]})
        remaining = await db.dictionary_history.count_documents({})
        return {"ok": True, "word": w, "remaining": remaining}

    @router.get("/word")
    async def word_info(request: Request, word: str):
        await require_admin(request, db)
        w = _clean_word(word)
        if not w:
            raise HTTPException(status_code=400, detail="word_required")
        return await _entry(w)

    @router.post("/entry")
    async def save_entry(request: Request, word: str = Form(...), ipa: str = Form(""),
                         file: Optional[UploadFile] = File(None)):
        await require_admin(request, db)
        w = _clean_word(word)
        ipa_clean = (ipa or "").strip()
        if not w:
            raise HTTPException(status_code=400, detail="word_required")
        if ipa_clean and not IPA_ALLOWED.match(ipa_clean):
            raise HTTPException(status_code=400, detail="invalid_ipa")
        if not ipa_clean and file is None:
            raise HTTPException(status_code=400, detail="ipa_or_audio_required")
        await _snapshot(w)
        base = cmu_ipa(w)
        ipa_final = ipa_clean or base
        is_custom = bool(ipa_clean) and ipa_clean != base
        doc = {"word": w, "ipa": ipa_final, "cmu_ipa": base, "ipa_custom": is_custom,
               "categories": classify_ipa(ipa_final), "status": "done", "updated_at": _now_iso()}
        # The coach's IPA drives ElevenLabs via phoneme tags; her own recording
        # is archived for reference but never played to members.
        phones = ipa_to_arpabet(ipa_final) if ipa_final else None
        if ipa_final and not phones:
            raise HTTPException(status_code=400, detail="invalid_ipa")
        if phones:
            arp = " ".join(phones)
            await db.pronunciation_prefs.update_one(
                {"word": w},
                {"$set": {"word": w, "arpabet": arp, "ipa": ipa_final,
                          "categories": classify_ipa(ipa_final),
                          "source": "dictionary", "updated_at": _now_iso()}},
                upsert=True)
            PREFERRED_ARPA[w] = arp
            doc["arpabet"] = arp
            # Drop generated (non-override) audio so the next play follows
            # the new phonemes.
            await db.audio_cache.delete_many(
                {"word": {"$in": [w, f"{w}#ph"]}, "manual_override": {"$ne": True}})
        if file is not None:
            raw = await file.read()
            if not raw:
                raise HTTPException(status_code=400, detail="empty_file")
            if len(raw) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="file_too_large_max_2mb")
            ct = (file.content_type or "").lower().split(";")[0].strip() or "audio/wav"
            if ct not in ALLOWED_AUDIO_TYPES:
                raise HTTPException(status_code=400, detail=f"unsupported_audio_type:{ct}")
            await db.audio_cache.update_one(
                {"word": f"{w}#human"},
                {"$set": {"word": f"{w}#human", "audio_b64": base64.b64encode(raw).decode("ascii"),
                          "manual_override": False, "content_type": ct, "byte_size": len(raw),
                          "created_at": _now_iso()}},
                upsert=True)
            # Re-voice the coach's take with the ElevenLabs voice (speech-to-
            # speech keeps her exact pronunciation). This becomes what members
            # hear for the word everywhere.
            try:
                revoiced = await asyncio.to_thread(revoice_recording, raw)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"elevenlabs_revoice_failed: {e}")
            await db.audio_cache.update_one(
                {"word": w},
                {"$set": {"word": w, "audio_b64": base64.b64encode(revoiced).decode("ascii"),
                          "manual_override": True, "source": "speech_to_speech",
                          "content_type": "audio/mpeg", "byte_size": len(revoiced),
                          "created_at": _now_iso()}},
                upsert=True)
            doc.update({"has_audio": True, "content_type": ct, "revoiced": True})
        else:
            existing = await db.dictionary_entries.find_one({"word": w}, {"_id": 0, "has_audio": 1})
            doc["has_audio"] = bool(existing and existing.get("has_audio"))
        await db.dictionary_entries.update_one({"word": w}, {"$set": doc}, upsert=True)
        if is_custom:
            CUSTOM_IPA[w] = ipa_final
        else:
            CUSTOM_IPA.pop(w, None)
        # Scene lines containing this word re-render with the correction next play.
        await db.turn_audio_cache.delete_many({"text": {"$regex": rf"\b{re.escape(w)}\b", "$options": "i"}})
        return {"ok": True, **doc}

    @router.post("/skip")
    async def skip(body: WordBody, request: Request):
        await require_admin(request, db)
        w = _clean_word(body.word)
        await _snapshot(w)
        await db.dictionary_entries.update_one(
            {"word": w}, {"$set": {"word": w, "status": "skipped", "updated_at": _now_iso()}}, upsert=True)
        return {"ok": True}

    @router.get("/entries")
    async def entries(request: Request, q: Optional[str] = None, limit: int = 50, offset: int = 0):
        await require_admin(request, db)
        query: dict = {"status": "done"}
        if q:
            query["word"] = {"$regex": "^" + re.escape(_clean_word(q))}
        total = await db.dictionary_entries.count_documents(query)
        docs = await db.dictionary_entries.find(query, {"_id": 0}).sort("word", 1) \
            .skip(max(0, offset)).to_list(max(1, min(limit, 200)))
        return {"total": total, "entries": docs, "stats": await _stats()}

    @router.post("/entries/delete")
    async def delete_entry(body: WordBody, request: Request):
        await require_admin(request, db)
        w = _clean_word(body.word)
        await db.dictionary_entries.delete_one({"word": w})
        await db.audio_cache.delete_many({"word": {"$in": [w, f"{w}#ph", f"{w}#human"]}})
        await db.pronunciation_prefs.delete_one({"word": w, "source": "dictionary"})
        PREFERRED_ARPA.pop(w, None)
        CUSTOM_IPA.pop(w, None)
        return {"ok": True}

    @router.get("/audio")
    async def audio(request: Request, word: str, which: str = "human"):
        await require_admin(request, db)
        w = _clean_word(word)
        q = {"word": w, "manual_override": True} if which == "eleven" else {"word": f"{w}#human"}
        a = await db.audio_cache.find_one(q, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="no_recording")
        return Response(content=base64.b64decode(a["audio_b64"]),
                        media_type=a.get("content_type") or "audio/mpeg")

    def _csv_bytes(rows: list) -> str:
        buf = io.StringIO()
        cols = ["word", "ipa", "cmu_ipa", "ipa_custom", "has_audio", "audio_file", "updated_at"]
        wr = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            ext = _EXT.get(r.get("content_type") or "", "mp3")
            r = {**r, "audio_file": f"audio/{r['word']}.{ext}" if r.get("has_audio") else ""}
            wr.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
        return buf.getvalue()

    @router.get("/export.csv")
    async def export_csv(request: Request):
        await require_admin(request, db)
        rows = await db.dictionary_entries.find({"status": "done"}, {"_id": 0}).sort("word", 1).to_list(200_000)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return Response(content=_csv_bytes(rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="dictionary-{stamp}.csv"'})

    @router.get("/export.zip")
    async def export_zip(request: Request):
        await require_admin(request, db)
        rows = await db.dictionary_entries.find({"status": "done"}, {"_id": 0}).sort("word", 1).to_list(200_000)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("dictionary.csv", _csv_bytes(rows))
            async for a in db.audio_cache.find({"word": {"$regex": "#human$"}}, {"_id": 0}):
                ext = _EXT.get(a.get("content_type") or "", "mp3")
                zf.writestr(f"audio/{a['word'][:-6]}.{ext}", base64.b64decode(a["audio_b64"]))
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return Response(content=buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="dictionary-{stamp}.zip"'})

    return router
