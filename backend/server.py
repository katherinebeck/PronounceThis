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
    turn_index: Optional[int] = None


class Turn(BaseModel):
    """A single continuous read: one speaker's dialogue (or one narration block)."""
    index: int
    speaker: Optional[str] = None
    text: str


class Scene(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    raw_text: str
    tokens: List[WordToken]
    turns: List[Turn] = Field(default_factory=list)
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


class TurnTTSResponse(BaseModel):
    scene_id: str
    turn_index: int
    speaker: Optional[str] = None
    audio_b64: str
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


# --- Turn detection ---------------------------------------------------------
# Matches "SPEAKER:" at the start of the text, right after a newline, or right
# after sentence-final punctuation. The speaker label is uppercase-ish and up
# to ~30 characters — enough for names like "MARY BETH" or "ANNOUNCER (V.O.)".
SPEAKER_INLINE_RE = re.compile(
    r"(?:^|[.!?]\s+|\n\s*)([A-Z][A-Z0-9 .'’\-]{0,30}?):[ \t]+"
)
# Screenplay style: a speaker label alone on its own line, all caps.
SPEAKER_SOLO_RE = re.compile(
    r"(?:^|\n)[ \t]*([A-Z][A-Z0-9 .'’\-]{1,30})[ \t]*(?:\([^)]{0,25}\))?[ \t]*\n"
)


def _clean_speaker(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip(" .:'’-")


def _push_turn(turns: List[Dict], speaker: Optional[str], body: str,
               start: int, end: int) -> None:
    body = body.strip()
    if not body:
        return
    # Merge with previous turn if same speaker and adjacent — one continuous read.
    if turns and turns[-1]["speaker"] == speaker:
        turns[-1]["text"] = (turns[-1]["text"] + " " + body).strip()
        turns[-1]["char_end"] = end
        return
    turns.append({
        "index": len(turns),
        "speaker": speaker,
        "text": body,
        "char_start": start,
        "char_end": end,
    })


def extract_turns(raw_text: str) -> List[Dict]:
    """Split a scene into speaker turns.

    Detects both screenplay style (speaker label on its own line) and inline
    style ("SPEAKER: dialogue"). Consecutive segments by the same speaker are
    merged so a natural pause only appears when the speaker changes.
    """
    if not raw_text.strip():
        return []

    # Prefer screenplay style if we find at least two labels on their own line.
    solo = list(SPEAKER_SOLO_RE.finditer(raw_text))
    if len(solo) >= 2:
        turns: List[Dict] = []
        first = solo[0]
        if first.start() > 0:
            _push_turn(turns, None, raw_text[:first.start()], 0, first.start())
        for i, m in enumerate(solo):
            speaker = _clean_speaker(m.group(1))
            body_start = m.end()
            body_end = solo[i + 1].start() if i + 1 < len(solo) else len(raw_text)
            _push_turn(turns, speaker, raw_text[body_start:body_end],
                       body_start, body_end)
        if turns:
            return turns

    # Inline style fallback.
    inline = list(SPEAKER_INLINE_RE.finditer(raw_text))
    if inline:
        turns = []
        first_label_start = inline[0].start(1)
        if first_label_start > 0:
            _push_turn(turns, None, raw_text[:first_label_start],
                       0, first_label_start)
        for i, m in enumerate(inline):
            speaker = _clean_speaker(m.group(1))
            body_start = m.end()
            body_end = inline[i + 1].start(1) if i + 1 < len(inline) else len(raw_text)
            _push_turn(turns, speaker, raw_text[body_start:body_end],
                       body_start, body_end)
        if turns:
            return turns

    # No speaker labels at all — one continuous narration turn.
    return [{
        "index": 0, "speaker": None,
        "text": raw_text.strip(),
        "char_start": 0, "char_end": len(raw_text),
    }]


def assign_token_turns(tokens: List[Dict], turns: List[Dict]) -> None:
    """Mutate `tokens` in-place, adding `turn_index` on each token based on
    its character position in the concatenated scene text.

    Tokens whose midpoint falls in the *gap* between two turns' [char_start,
    char_end) ranges — i.e. the speaker label text like "FRIEND:" — get
    `turn_index = None`, so the UI can skip rendering them (the speaker is
    already shown as a header above each turn).
    """
    if not turns:
        return
    pos = 0
    for tok in tokens:
        tlen = len(tok.get("text", ""))
        mid = pos + max(0, tlen // 2)
        assigned = None
        for t in turns:
            if t["char_start"] <= mid < t["char_end"]:
                assigned = t["index"]
                break
        tok["turn_index"] = assigned
        pos += tlen


def build_turns_for_scene(doc: Dict) -> List[Dict]:
    """Compute turns from stored raw_text and attach turn_index to tokens.
    Returns the public turn dicts (index, speaker, text) — internal offsets
    are dropped."""
    turns = extract_turns(doc.get("raw_text", "") or "")
    tokens = doc.get("tokens") or []
    assign_token_turns(tokens, turns)
    return [{"index": t["index"], "speaker": t["speaker"], "text": t["text"]}
            for t in turns]


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

    # Compute turns and stamp turn_index onto each token (in place on the model).
    doc = scene.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    turns_public = build_turns_for_scene(doc)
    doc["turns"] = turns_public
    await db.scenes.insert_one(doc)

    # Return a fresh Scene with turns applied.
    return Scene(**doc)


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
    # Compute turns fresh on every fetch so parsing improvements are picked up
    # automatically for scenes uploaded before the feature landed.
    doc["turns"] = build_turns_for_scene(doc)
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


def _synthesize(text: str) -> bytes:
    """Blocking ElevenLabs synthesis for an arbitrary line of text."""
    client = _eleven_client()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    stream = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    buf = bytearray()
    for chunk in stream:
        if chunk:
            buf.extend(chunk)
    return bytes(buf)


@api_router.post("/scenes/{scene_id}/turns/{turn_index}/tts",
                 response_model=TurnTTSResponse)
async def tts_turn(scene_id: str, turn_index: int):
    """Generate (and cache) audio for one continuous speaker turn."""
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")

    turns = extract_turns(doc.get("raw_text", "") or "")
    if turn_index < 0 or turn_index >= len(turns):
        raise HTTPException(status_code=404, detail="Turn not found")
    turn = turns[turn_index]

    cache_key = f"{scene_id}:{turn_index}"
    cached = await db.turn_audio_cache.find_one({"key": cache_key}, {"_id": 0})
    if cached and cached.get("audio_b64"):
        return TurnTTSResponse(
            scene_id=scene_id, turn_index=turn_index,
            speaker=turn["speaker"], audio_b64=cached["audio_b64"], cached=True,
        )

    try:
        audio_bytes = await asyncio.to_thread(_synthesize, turn["text"])
    except Exception as e:
        logger.exception("ElevenLabs turn TTS error")
        raise HTTPException(status_code=502, detail=f"TTS failed: {e}")

    if not audio_bytes:
        raise HTTPException(status_code=502, detail="TTS returned empty audio")

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    async with _tts_lock:
        await db.turn_audio_cache.update_one(
            {"key": cache_key},
            {"$set": {"key": cache_key, "scene_id": scene_id,
                      "turn_index": turn_index, "audio_b64": audio_b64,
                      "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return TurnTTSResponse(
        scene_id=scene_id, turn_index=turn_index,
        speaker=turn["speaker"], audio_b64=audio_b64, cached=False,
    )


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
