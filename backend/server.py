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
from caption_search import CaptionSearchService

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# --- DB ---------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

# --- App --------------------------------------------------------------------
app = FastAPI(title="American Accent Coach")
api_router = APIRouter(prefix="/api")

caption_service = CaptionSearchService(db)

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
    is_proper_noun: bool = False


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


class PronounceResponse(BaseModel):
    """Result of a single-word IPA lookup (no audio)."""
    word: str
    normalized: str
    ipa: Optional[str]
    arpabet: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    source: str  # "cmu" | "llm" | "none"


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


async def extract_dialogue_via_llm(raw_text: str) -> Optional[Dict]:
    """Use Claude Sonnet 4.5 to pull SPOKEN dialogue AND proper nouns out of a
    script excerpt.

    Returns `{"dialogue": [{speaker, text, index}, ...],
              "proper_nouns": [str, ...]}` in reading order, or None if the
    LLM was unavailable / returned garbage. Stage directions, scene headings,
    action lines, and parentheticals are dropped from dialogue. Consecutive
    lines by the same speaker are merged into a single entry.
    """
    if not raw_text.strip():
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        logger.warning("emergentintegrations import failed: %s", e)
        return None

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return None

    system = (
        "You extract SPOKEN dialogue from a script excerpt (screenplay, "
        "audition scene, or play). Two jobs:\n\n"
        "(1) DIALOGUE — identify what characters actually SAY out loud, and "
        "remove everything else.\n"
        "  STRIP OUT:\n"
        "  • Scene headings (EXT./INT./FADE IN/CUT TO)\n"
        "  • Stage directions and action lines (e.g. 'A beat.', 'She turns.', "
        "'The ANNOUNCER steps forward.', 'The crowd cheers.')\n"
        "  • Parentheticals inside dialogue (e.g. '(nervously)', '(V.O.)', "
        "'(beat)')\n"
        "  • Any narration or descriptive prose\n"
        "  KEEP:\n"
        "  • Every line spoken aloud by a character, exactly as written\n"
        "  • Speaker names capitalized as they appear (e.g. 'ELIZA', 'MARK')\n"
        "  MERGE consecutive same-speaker lines into ONE entry (single space "
        "separator).\n\n"
        "(2) PROPER NOUNS — from the ENTIRE excerpt (dialogue AND stage "
        "directions), collect every proper noun a coach would want a reference "
        "pronunciation for: character names, place names, brand names, "
        "specific titles. Include single words AND multi-word names "
        "(e.g. 'Miss Whitmore', 'New Orleans', 'Independence Hall'). "
        "Preserve their exact original capitalization. Deduplicate.\n\n"
        "OUTPUT — exactly one JSON object, no markdown, no prose:\n"
        "{\n"
        "  \"dialogue\": [ {\"speaker\": \"NAME\", \"text\": \"...\"}, ... ],\n"
        "  \"proper_nouns\": [\"Eliza\", \"Miss Whitmore\", \"Independence\"]\n"
        "}\n"
        "If no dialogue is present, return dialogue: []. If no proper nouns, "
        "return proper_nouns: []."
    )
    chat = LlmChat(
        api_key=api_key,
        session_id=f"dialogue-{uuid.uuid4()}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    try:
        raw = await chat.send_message(UserMessage(text=raw_text))
    except Exception as e:
        logger.warning("LLM dialogue extraction failed: %s", e)
        return None

    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned,
                     flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
    except Exception as e:
        logger.warning("LLM dialogue parse failed: %s :: %s", e, cleaned[:200])
        return None
    if not isinstance(data, dict):
        return None

    raw_dialogue = data.get("dialogue")
    if not isinstance(raw_dialogue, list):
        return None

    cleaned_items: List[Dict] = []
    for item in raw_dialogue:
        if not isinstance(item, dict):
            continue
        spk = str(item.get("speaker", "")).strip() or None
        txt = re.sub(r"\s+", " ", str(item.get("text", "")).strip())
        if not txt:
            continue
        txt = re.sub(r"\([^)]*\)", "", txt).strip()
        if not txt:
            continue
        cleaned_items.append({"speaker": spk, "text": txt})

    merged: List[Dict] = []
    for item in cleaned_items:
        if merged and merged[-1]["speaker"] == item["speaker"]:
            merged[-1]["text"] = (merged[-1]["text"] + " " + item["text"]).strip()
        else:
            merged.append(dict(item))
    for i, m in enumerate(merged):
        m["index"] = i

    proper_nouns_raw = data.get("proper_nouns") or []
    proper_nouns: List[str] = []
    seen_pn = set()
    if isinstance(proper_nouns_raw, list):
        for pn in proper_nouns_raw:
            s = str(pn).strip()
            if not s:
                continue
            key = s.lower()
            if key in seen_pn:
                continue
            seen_pn.add(key)
            proper_nouns.append(s)

    return {"dialogue": merged, "proper_nouns": proper_nouns}


def _proper_noun_word_set(proper_nouns: List[str]) -> set:
    """Return a set of case-sensitive letters-only individual words from the
    proper-noun list. Multi-word names like 'Miss Whitmore' become {'Miss',
    'Whitmore'}. Words that don't start uppercase (e.g. articles Claude may
    have left in) are dropped."""
    words = set()
    for pn in proper_nouns or []:
        for w in re.findall(r"[A-Za-z]+", pn):
            if len(w) > 1 and w[0].isupper():
                words.add(w)
    return words


def _token_is_proper_noun(tok_text: str, pn_words: set) -> bool:
    """A token is a proper noun if its letters-only, case-preserved form is
    in `pn_words` — with a possessive fallback so 'Mary's' matches 'Mary'."""
    letters = re.sub(r"[^A-Za-z]", "", tok_text or "")
    if len(letters) < 2 or not letters[0].isupper():
        return False
    if letters in pn_words:
        return True
    if letters.endswith("s") and letters[:-1] in pn_words:
        return True
    return False


def _tokens_for_dialogue(dialogue: List[Dict],
                         proper_nouns: List[str]) -> tuple:
    """Turn a list of `{speaker, text, index}` items into a flat token list
    ready to render + a public `turns` list. Returns (tokens, turns_public,
    unknown_norm_words). Each token carries `turn_index` pre-assigned; a
    single non-word `\n\n` separator between turns has turn_index=None so it
    doesn't render inside any turn's flow.
    """
    pn_words = _proper_noun_word_set(proper_nouns)
    tokens: List[WordToken] = []
    turns_public: List[Dict] = []
    unknown: List[str] = []
    for item in dialogue:
        ti = item["index"]
        if tokens:
            tokens.append(WordToken(text="\n\n", is_word=False,
                                    turn_index=None))
        for tok in tokenize_scene(item["text"]):
            if not tok["is_word"]:
                tokens.append(WordToken(text=tok["text"], is_word=False,
                                        turn_index=ti))
                continue
            norm = normalize_word(tok["text"])
            ipa, arpa, cats = transcribe_word(norm) if norm else (None, [], [])
            wt = WordToken(
                text=tok["text"], is_word=True, ipa=ipa,
                arpabet=arpa, categories=cats,
                source="cmu" if ipa else "none",
                turn_index=ti,
                is_proper_noun=_token_is_proper_noun(tok["text"], pn_words),
            )
            if not ipa and norm:
                unknown.append(norm)
            tokens.append(wt)
        turns_public.append({
            "index": ti, "speaker": item["speaker"], "text": item["text"],
        })
    return tokens, turns_public, unknown


async def _apply_llm_ipa_fallback(tokens: List[WordToken],
                                  unknown_words: List[str]) -> None:
    unique = list(dict.fromkeys(unknown_words))[:80]
    if not unique:
        return
    llm_map = await llm_transcribe_words(unique)
    if not llm_map:
        return
    for wt in tokens:
        if wt.is_word and not wt.ipa:
            key = normalize_word(wt.text)
            if key in llm_map:
                wt.ipa = llm_map[key]
                wt.source = "llm"


async def build_dialogue_only_scene(raw_text: str) -> tuple:
    """Return (tokens, turns_public, dialogue, proper_nouns) built from
    LLM-extracted dialogue, with a regex fallback if the LLM is unavailable.

    Raises HTTPException(400) if no dialogue at all can be extracted.
    """
    llm_out = await extract_dialogue_via_llm(raw_text)
    if llm_out is None:
        dialogue: List[Dict] = []
        proper_nouns: List[str] = []
    else:
        dialogue = llm_out.get("dialogue") or []
        proper_nouns = llm_out.get("proper_nouns") or []

    if not dialogue:
        # Fallback: regex-detect turns and drop narration.
        regex_turns = extract_turns(raw_text)
        dialogue = [
            {"speaker": t["speaker"], "text": t["text"], "index": 0}
            for t in regex_turns if t["speaker"]
        ]
        for i, d in enumerate(dialogue):
            d["index"] = i

    if not dialogue:
        raise HTTPException(
            status_code=400,
            detail=(
                "No spoken dialogue was detected in this PDF. Make sure it "
                "contains character lines like 'ELIZA: Wait!' or a screenplay "
                "with character names above each line."
            ),
        )

    tokens, turns_public, unknown = _tokens_for_dialogue(dialogue, proper_nouns)
    await _apply_llm_ipa_fallback(tokens, unknown)
    return tokens, turns_public, dialogue, proper_nouns


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


@api_router.get("/pronounce", response_model=PronounceResponse)
async def pronounce(word: str):
    """Return IPA + ARPABET + sound categories for a single word.

    Uses the CMU Pronouncing Dictionary first; falls back to Claude for
    out-of-dictionary words (names, invented spellings). Does NOT synthesize
    audio — the frontend calls POST /api/tts for that separately.
    """
    raw = (word or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="word is required")

    norm = normalize_word(raw)
    if not norm:
        raise HTTPException(
            status_code=400,
            detail="Please enter a real word (letters only).",
        )

    ipa, arpa, cats = transcribe_word(norm)
    if ipa:
        return PronounceResponse(
            word=raw, normalized=norm, ipa=ipa,
            arpabet=arpa, categories=cats, source="cmu",
        )

    # CMU miss → Claude fallback.
    llm_map = await llm_transcribe_words([norm])
    llm_ipa = llm_map.get(norm)
    return PronounceResponse(
        word=raw, normalized=norm, ipa=llm_ipa,
        arpabet=[], categories=[],
        source="llm" if llm_ipa else "none",
    )


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

    # Dialogue-only pipeline: LLM extracts spoken lines + proper nouns, then
    # we tokenize just those and run IPA over them. Stage directions and
    # narration are dropped.
    typed_tokens, turns_public, dialogue, proper_nouns = (
        await build_dialogue_only_scene(text)
    )

    scene_title = title or (
        file.filename.rsplit(".", 1)[0] if file.filename else "Untitled scene"
    )
    scene = Scene(
        title=scene_title, raw_text=text, tokens=typed_tokens,
        turns=[Turn(**t) for t in turns_public],
    )

    doc = scene.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    doc["dialogue_only"] = True
    doc["dialogue"] = dialogue
    doc["proper_nouns"] = proper_nouns
    await db.scenes.insert_one(doc)

    return Scene(**doc)


async def _ensure_dialogue_only(doc: Dict) -> Dict:
    """Backfill a pre-existing scene to the dialogue-only representation.

    Older scenes were tokenized from the whole raw text (including stage
    directions). On first GET after the migration lands, run the dialogue
    extractor once, rebuild tokens, drop any cached turn audio (its text no
    longer matches), and persist the new shape.
    """
    if doc.get("dialogue_only") and "proper_nouns" in doc:
        return doc
    raw_text = doc.get("raw_text", "") or ""
    try:
        typed_tokens, turns_public, dialogue, proper_nouns = (
            await build_dialogue_only_scene(raw_text)
        )
    except HTTPException:
        # Couldn't find any dialogue — leave the scene untouched so the app
        # doesn't blow up; upload flow already blocks pure-narration PDFs.
        logger.warning("Dialogue migration skipped for scene %s (no dialogue).",
                       doc.get("id"))
        return doc

    new_tokens = [wt.model_dump() for wt in typed_tokens]
    new_turns = turns_public
    await db.scenes.update_one(
        {"id": doc["id"]},
        {"$set": {
            "tokens": new_tokens, "turns": new_turns,
            "dialogue_only": True, "dialogue": dialogue,
            "proper_nouns": proper_nouns,
        }},
    )
    # Invalidate stale turn audio — indices and text have changed.
    await db.turn_audio_cache.delete_many({"scene_id": doc["id"]})
    doc["tokens"] = new_tokens
    doc["turns"] = new_turns
    doc["dialogue_only"] = True
    doc["dialogue"] = dialogue
    doc["proper_nouns"] = proper_nouns
    return doc


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
    doc = await _ensure_dialogue_only(doc)
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    return Scene(**doc)


@api_router.post("/scenes/{scene_id}/reparse", response_model=Scene)
async def reparse_scene(scene_id: str):
    """Force a re-extraction of dialogue for a saved scene. Useful if the
    original extraction missed lines or grouped them oddly."""
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")
    doc["dialogue_only"] = False  # Force re-run.
    doc = await _ensure_dialogue_only(doc)
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
        # Force a declarative reading: appending a period tells the TTS
        # engine to fall in pitch at the end rather than uptalk-question
        # every isolated word ("popular?" → "popular.").
        spoken = word if word.endswith((".", "!", "?")) else f"{word}."
        stream = client.text_to_speech.convert(
            text=spoken,
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


# --- Caption search (YouGlish replacement) ---------------------------------
@api_router.get("/caption-search")
async def caption_search(q: str, limit: int = 6, refresh: bool = False):
    """Search curated American-speaker YouTube channels for videos where the
    given word/phrase is actually spoken in the captions."""
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Missing query.")
    if len(q) > 80:
        raise HTTPException(status_code=400, detail="Query too long.")
    return await caption_service.search(q, limit=max(1, min(limit, 10)),
                                        force_refresh=refresh)


@api_router.post("/scenes/{scene_id}/turns/{turn_index}/tts",
                 response_model=TurnTTSResponse)
async def tts_turn(scene_id: str, turn_index: int):
    """Generate (and cache) audio for one continuous speaker turn.

    Uses the persisted dialogue-only turns on the scene doc so the audio
    always matches exactly what the UI shows for the same index. Legacy
    scenes are migrated on the fly.
    """
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")
    doc = await _ensure_dialogue_only(doc)

    turns = doc.get("turns") or []
    if turn_index < 0 or turn_index >= len(turns):
        raise HTTPException(status_code=404, detail="Turn not found")
    turn = turns[turn_index]

    cache_key = f"{scene_id}:{turn_index}"
    cached = await db.turn_audio_cache.find_one({"key": cache_key}, {"_id": 0})
    if cached and cached.get("audio_b64"):
        return TurnTTSResponse(
            scene_id=scene_id, turn_index=turn_index,
            speaker=turn.get("speaker"), audio_b64=cached["audio_b64"],
            cached=True,
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
        speaker=turn.get("speaker"), audio_b64=audio_b64, cached=False,
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
