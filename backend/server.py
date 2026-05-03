"""Backend for the American Accent Coach app.

Endpoints (all prefixed /api):
- POST /api/scenes/upload         Upload a PDF, return parsed + transcribed scene
- GET  /api/scenes                List all saved scenes
- GET  /api/scenes/{scene_id}     Fetch one scene
- DELETE /api/scenes/{scene_id}   Delete a scene
- GET  /api/scenes/{scene_id}/laundry-list?sound=...  Filtered word list
- POST /api/tts                   Generate (and cache) ElevenLabs audio for a word
- GET  /api/sound-categories      Static list of practice categories
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from starlette.middleware.cors import CORSMiddleware

from phonetics import (
    SOUND_CATEGORIES,
    arpabet_to_ipa,
    classify_word,
    get_arpabet,
    transcribe_word,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# --- DB ---------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

# --- App --------------------------------------------------------------------
app = FastAPI(title="American Accent Coach")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# --- Models -----------------------------------------------------------------
class WordToken(BaseModel):
    """One token in a scene. May be a real word (`is_word=True`) or punctuation
    / whitespace (`is_word=False`). Real words carry IPA + sound categories."""
    model_config = ConfigDict(extra="ignore")
    text: str
    is_word: bool = True
    ipa: Optional[str] = None
    arpabet: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    source: str = "cmu"  # "cmu" | "llm" | "none"


class Scene(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    raw_text: str
    tokens: List[WordToken]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SceneSummary(BaseModel):
    id: str
    title: str
    word_count: int
    created_at: datetime


class TTSRequest(BaseModel):
    word: str


class TTSResponse(BaseModel):
    word: str
    audio_b64: str  # raw base64 (no data: prefix)
    mime: str = "audio/mpeg"
    cached: bool = False


# --- Helpers ----------------------------------------------------------------
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


def tokenize_scene(text: str) -> List[Dict]:
    """Split text into ordered tokens preserving punctuation & whitespace.

    Real word tokens have `is_word=True`; everything else (spaces, line breaks,
    punctuation) is preserved so the frontend can render the scene faithfully.
    """
    tokens: List[Dict] = []
    last = 0
    for m in WORD_RE.finditer(text):
        if m.start() > last:
            tokens.append({"text": text[last:m.start()], "is_word": False})
        tokens.append({"text": m.group(0), "is_word": True})
        last = m.end()
    if last < len(text):
        tokens.append({"text": text[last:], "is_word": False})
    return tokens


def normalize_word(w: str) -> str:
    return re.sub(r"[^A-Za-z']", "", w).lower()


async def llm_transcribe_words(words: List[str]) -> Dict[str, str]:
    """Use Claude Sonnet 4.5 to transcribe out-of-dictionary words to American IPA.

    Returns a mapping of `word -> ipa string`. Failures fall back to {} so the
    caller can render the word without IPA rather than crash the upload.
    """
    if not words:
        return {}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        logger.warning("emergentintegrations import failed: %s", e)
        return {}

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return {}

    system = (
        "You are a phonetic transcription engine for General American English. "
        "Given a JSON array of words, return ONLY a JSON object mapping each "
        "word to its American English IPA transcription using narrow IPA "
        "symbols (e.g. ɹ, ɝ, ɑ, æ, ʌ, ə, eɪ, oʊ, aɪ, aʊ, ɔɪ, ʃ, ʒ, θ, ð, "
        "tʃ, dʒ, ŋ, ɫ for dark L). Use ˈ for primary stress and ˌ for "
        "secondary. No commentary, no markdown — just JSON."
    )
    chat = LlmChat(
        api_key=api_key,
        session_id=f"ipa-{uuid.uuid4()}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    msg = UserMessage(text=json.dumps(words))
    try:
        raw = await chat.send_message(msg)
    except Exception as e:
        logger.warning("LLM IPA fallback failed: %s", e)
        return {}

    # Strip code fences if present and parse the JSON object.
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {k.lower(): str(v) for k, v in data.items()}
    except Exception as e:
        logger.warning("LLM IPA parse failed: %s :: %s", e, cleaned[:200])
    return {}


# --- Routes -----------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"message": "American Accent Coach API"}


@api_router.get("/sound-categories")
async def sound_categories():
    return {"categories": SOUND_CATEGORIES}


@api_router.post("/scenes/upload", response_model=Scene)
async def upload_scene(file: UploadFile = File(...), title: Optional[str] = None):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    raw = await file.read()
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:
        logger.exception("PDF parse error")
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {e}")

    text = "\n\n".join(pages).strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail="No text was found in this PDF. Only text-based PDFs are supported.",
        )

    raw_tokens = tokenize_scene(text)

    # First pass — CMU dictionary.
    unknown: List[str] = []
    typed_tokens: List[WordToken] = []
    for tok in raw_tokens:
        if not tok["is_word"]:
            typed_tokens.append(WordToken(text=tok["text"], is_word=False))
            continue
        norm = normalize_word(tok["text"])
        ipa, arpa, cats = transcribe_word(norm) if norm else (None, [], [])
        wt = WordToken(
            text=tok["text"],
            is_word=True,
            ipa=ipa,
            arpabet=arpa,
            categories=cats,
            source="cmu" if ipa else "none",
        )
        if not ipa and norm:
            unknown.append(norm)
        typed_tokens.append(wt)

    # Second pass — LLM fallback for unknown words (deduped, capped).
    unique_unknown = list(dict.fromkeys(unknown))[:80]
    llm_map = await llm_transcribe_words(unique_unknown) if unique_unknown else {}
    if llm_map:
        for wt in typed_tokens:
            if wt.is_word and not wt.ipa:
                key = normalize_word(wt.text)
                if key in llm_map:
                    wt.ipa = llm_map[key]
                    wt.source = "llm"

    scene_title = title or (file.filename.rsplit(".", 1)[0] if file.filename else "Untitled scene")
    scene = Scene(title=scene_title, raw_text=text, tokens=typed_tokens)

    doc = scene.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.scenes.insert_one(doc)

    return scene


@api_router.get("/scenes", response_model=List[SceneSummary])
async def list_scenes():
    cursor = db.scenes.find({}, {"_id": 0, "id": 1, "title": 1, "tokens": 1, "created_at": 1})
    items = await cursor.to_list(500)
    out: List[SceneSummary] = []
    for s in items:
        word_count = sum(1 for t in s.get("tokens", []) if t.get("is_word"))
        ts = s["created_at"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        out.append(SceneSummary(id=s["id"], title=s["title"],
                                word_count=word_count, created_at=ts))
    out.sort(key=lambda x: x.created_at, reverse=True)
    return out


@api_router.get("/scenes/{scene_id}", response_model=Scene)
async def get_scene(scene_id: str):
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    return Scene(**doc)


@api_router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str):
    res = await db.scenes.delete_one({"id": scene_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Scene not found")
    return {"ok": True}


@api_router.get("/scenes/{scene_id}/laundry-list")
async def laundry_list(scene_id: str, sound: str):
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")

    seen: set = set()
    matches: List[Dict] = []
    for t in doc.get("tokens", []):
        if not t.get("is_word"):
            continue
        if sound in (t.get("categories") or []):
            key = normalize_word(t["text"])
            if key in seen:
                continue
            seen.add(key)
            matches.append({
                "text": t["text"],
                "ipa": t.get("ipa"),
                "categories": t.get("categories", []),
            })
    return {"sound": sound, "count": len(matches), "words": matches}


# --- TTS --------------------------------------------------------------------
_tts_lock = asyncio.Lock()


def _eleven_client():
    from elevenlabs.client import ElevenLabs
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not configured")
    return ElevenLabs(api_key=api_key)


@api_router.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest):
    word = (req.word or "").strip()
    if not word:
        raise HTTPException(status_code=400, detail="word is required")

    cache_key = word.lower()
    cached = await db.audio_cache.find_one({"word": cache_key}, {"_id": 0})
    if cached and cached.get("audio_b64"):
        return TTSResponse(word=word, audio_b64=cached["audio_b64"], cached=True)

    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    def _generate() -> bytes:
        client = _eleven_client()
        # ElevenLabs SDK is sync; collect chunks into one mp3 blob.
        stream = client.text_to_speech.convert(
            text=word,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        buf = bytearray()
        for chunk in stream:
            if chunk:
                buf.extend(chunk)
        return bytes(buf)

    try:
        audio_bytes = await asyncio.to_thread(_generate)
    except Exception as e:
        logger.exception("ElevenLabs TTS error")
        raise HTTPException(status_code=502, detail=f"TTS failed: {e}")

    if not audio_bytes:
        raise HTTPException(status_code=502, detail="TTS returned empty audio")

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    async with _tts_lock:
        await db.audio_cache.update_one(
            {"word": cache_key},
            {"$set": {"word": cache_key, "audio_b64": audio_b64,
                      "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return TTSResponse(word=word, audio_b64=audio_b64, cached=False)


# --- Mount ------------------------------------------------------------------
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
