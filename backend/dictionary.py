"""Admin "My Dictionary": the coach walks the CMU word list alphabetically,
records each word and confirms/edits its IPA. Saved entries drive display
(CUSTOM_IPA) and playback (audio_cache manual overrides)."""
from __future__ import annotations

import base64
import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from auth import require_admin
from phonetics import CUSTOM_IPA, classify_ipa, cmu_ipa, cmu_word_list, cmu_words_by_frequency

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
                       "audio/webm", "audio/ogg", "audio/mp4", "audio/m4a"}
MAX_AUDIO_BYTES = 2 * 1024 * 1024
_EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/m4a": "m4a"}
IPA_ALLOWED = re.compile(r"^[a-zɑæɐɛəɜɝɚɪiɔoʊuʌʔbdðfɡghjklɫmnŋpɹrsʃtθvwzʒɾ\u0329ˈˌː.\s]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_word(w: str) -> str:
    return re.sub(r"[^a-z']", "", (w or "").lower().strip())


class WordBody(BaseModel):
    word: str


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


def create_dictionary_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(prefix="/admin/dictionary", tags=["dictionary"])

    async def _stats() -> dict:
        done = await db.dictionary_entries.count_documents({"status": "done"})
        recorded = await db.dictionary_entries.count_documents({"status": "done", "has_audio": True})
        skipped = await db.dictionary_entries.count_documents({"status": "skipped"})
        return {"total": len(cmu_word_list()), "done": done, "recorded": recorded, "skipped": skipped}

    async def _entry(word: str) -> dict:
        e = await db.dictionary_entries.find_one({"word": word}, {"_id": 0}) or {}
        ipa = e.get("ipa") or cmu_ipa(word)
        return {"word": word, "ipa": ipa, "cmu_ipa": cmu_ipa(word),
                "ipa_custom": bool(e.get("ipa_custom")), "has_audio": bool(e.get("has_audio")),
                "status": e.get("status"), "in_cmu": bool(cmu_ipa(word))}

    @router.get("/queue")
    async def queue(request: Request, start: Optional[str] = None, limit: int = 12):
        await require_admin(request, db)
        words = cmu_words_by_frequency()
        pos = 0
        if start:
            try:
                pos = words.index(_clean_word(start))
            except ValueError:
                pos = 0
        limit = max(1, min(limit, 50))
        out: list = []
        while pos < len(words) and len(out) < limit:
            chunk = words[pos:pos + 400]
            pos += len(chunk)
            handled = {e["word"] async for e in db.dictionary_entries.find(
                {"word": {"$in": chunk}, "status": {"$in": ["done", "skipped"]}}, {"_id": 0, "word": 1})}
            for w in chunk:
                if w not in handled:
                    out.append({"word": w, "ipa": cmu_ipa(w)})
                    if len(out) >= limit:
                        break
        return {"words": out, "stats": await _stats()}

    @router.get("/word")
    async def word_info(request: Request, word: str):
        await require_admin(request, db)
        w = _clean_word(word)
        if not w:
            raise HTTPException(status_code=400, detail="word_required")
        return await _entry(w)

    @router.post("/entry")
    async def save_entry(request: Request, word: str = Form(...), ipa: str = Form(...),
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
        base = cmu_ipa(w)
        ipa_final = ipa_clean or base
        is_custom = bool(ipa_clean) and ipa_clean != base
        doc = {"word": w, "ipa": ipa_final, "cmu_ipa": base, "ipa_custom": is_custom,
               "categories": classify_ipa(ipa_final), "status": "done", "updated_at": _now_iso()}
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
                {"word": w},
                {"$set": {"word": w, "audio_b64": base64.b64encode(raw).decode("ascii"),
                          "manual_override": True, "content_type": ct, "byte_size": len(raw),
                          "created_at": _now_iso()}},
                upsert=True)
            doc.update({"has_audio": True, "content_type": ct})
        else:
            existing = await db.dictionary_entries.find_one({"word": w}, {"_id": 0, "has_audio": 1})
            doc["has_audio"] = bool(existing and existing.get("has_audio"))
        await db.dictionary_entries.update_one({"word": w}, {"$set": doc}, upsert=True)
        if is_custom:
            CUSTOM_IPA[w] = ipa_final
        else:
            CUSTOM_IPA.pop(w, None)
        return {"ok": True, **doc}

    @router.post("/skip")
    async def skip(body: WordBody, request: Request):
        await require_admin(request, db)
        w = _clean_word(body.word)
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
        await db.audio_cache.delete_one({"word": w, "manual_override": True})
        CUSTOM_IPA.pop(w, None)
        return {"ok": True}

    @router.get("/audio")
    async def audio(request: Request, word: str):
        await require_admin(request, db)
        a = await db.audio_cache.find_one({"word": _clean_word(word), "manual_override": True}, {"_id": 0})
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
            async for a in db.audio_cache.find({"manual_override": True}, {"_id": 0}):
                if "#" in a["word"]:
                    continue
                ext = _EXT.get(a.get("content_type") or "", "mp3")
                zf.writestr(f"audio/{a['word']}.{ext}", base64.b64decode(a["audio_b64"]))
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return Response(content=buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="dictionary-{stamp}.zip"'})

    return router
