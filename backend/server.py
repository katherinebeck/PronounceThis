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
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from phonetics import (
    PREFERRED_ARPA,
    SOUND_CATEGORIES,
    arpabet_to_ipa,
    arpabet_to_respelling,
    classify_ipa,
    classify_word,
    get_arpabet,
    transcribe_word,
)
from caption_search import CaptionSearchService
from wiktionary import WiktionaryIPA
import llm
from auth import (
    create_auth_router,
    require_access,
    require_login,
    require_subscriber,
    consume_trial,
    ensure_indexes as ensure_auth_indexes,
)
from kajabi import create_kajabi_router
from admin import create_admin_router
from stripe_payments import create_stripe_router

# --- DB ---------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

# --- App --------------------------------------------------------------------
app = FastAPI(title="American Accent Prep")
api_router = APIRouter(prefix="/api")

caption_service = CaptionSearchService(db)
wiktionary_ipa = WiktionaryIPA(db)

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
    # Proper nouns: drive pronunciation from the dictionary via phoneme tags.
    # Ordinary words: plain multilingual synthesis (more natural for
    # isolated function words like "in" / "because").
    phonetic: bool = False


class TTSResponse(BaseModel):
    word: str
    audio_b64: str  # raw base64 (no data: prefix)
    mime: str = "audio/mpeg"
    cached: bool = False
    # True when this audio came from an admin-uploaded manual pronunciation
    # override rather than ElevenLabs. The frontend uses this to decide
    # whether to also nudge the user toward Real Speakers.
    manual_override: bool = False


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
    if not raw_text.strip() or not llm.is_configured():
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
    raw = await llm.complete(system, raw_text)
    if raw is None:
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
    # Wiktionary (General American IPA) first; Claude only for what's left.
    wik_map = await wiktionary_ipa.lookup_many(unique)
    remaining = [w for w in unique if w.lower() not in wik_map]
    llm_map = await llm_transcribe_words(remaining) if remaining else {}
    for wt in tokens:
        if wt.is_word and not wt.ipa:
            key = normalize_word(wt.text)
            if key in wik_map:
                wt.ipa, wt.source = wik_map[key], "wiktionary"
            elif key in llm_map:
                wt.ipa, wt.source = llm_map[key], "llm"
            else:
                continue
            wt.categories = classify_ipa(wt.ipa)


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
    if not words or not llm.is_configured():
        return {}

    system = (
        "You are a phonetic transcription engine for General American English. "
        "Given a JSON array of words, return ONLY a JSON object mapping each "
        "word to its American English IPA transcription using narrow IPA "
        "symbols (e.g. ɹ, ɝ, ɑ, æ, ʌ, ə, eɪ, oʊ, aɪ, aʊ, ɔɪ, ʃ, ʒ, θ, ð, "
        "tʃ, dʒ, ŋ, ɫ for dark L). Use ˈ for primary stress and ˌ for "
        "secondary. No commentary, no markdown — just JSON."
    )
    raw = await llm.complete(system, json.dumps(words))
    if raw is None:
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
    return {"message": "American Accent Prep API"}


@api_router.get("/sound-categories")
async def sound_categories():
    return {"categories": SOUND_CATEGORIES}


@api_router.get("/pronounce", response_model=PronounceResponse)
async def pronounce(word: str):
    """Return IPA + ARPABET + sound categories for a single word or short phrase.

    Uses the CMU Pronouncing Dictionary first; falls back to Claude for
    out-of-dictionary words (names, invented spellings). Does NOT synthesize
    audio — the frontend calls POST /api/tts for that separately.

    Multi-word inputs (e.g., "los angeles") are handled by looking up each
    word in CMU and concatenating; only if a word is missing from CMU do we
    fall back to the slow LLM path for the whole phrase.
    """
    raw = (word or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="word is required")

    # Split on whitespace so multi-word queries hit the CMU dict per word.
    parts = [p for p in re.split(r"\s+", raw) if p]
    if not parts:
        raise HTTPException(
            status_code=400,
            detail="Please enter a real word (letters only).",
        )

    norm_parts = [normalize_word(p) for p in parts]
    if not all(norm_parts):
        raise HTTPException(
            status_code=400,
            detail="Please enter a real word (letters only).",
        )
    norm = "".join(norm_parts) if len(norm_parts) == 1 else " ".join(norm_parts)

    # Multi-word: try per-word CMU lookup and stitch. Fast path — no LLM.
    if len(parts) > 1:
        ipa_pieces: List[str] = []
        arpa_pieces: List[str] = []
        cats_set: List[str] = []
        all_hit = True
        for np in norm_parts:
            w_ipa, w_arpa, w_cats = transcribe_word(np)
            if not w_ipa:
                all_hit = False
                break
            ipa_pieces.append(w_ipa)
            arpa_pieces.extend(w_arpa)
            for c in w_cats:
                if c not in cats_set:
                    cats_set.append(c)
        if all_hit:
            return PronounceResponse(
                word=raw, normalized=norm, ipa=" ".join(ipa_pieces),
                arpabet=arpa_pieces, categories=cats_set, source="cmu",
            )

    # Single word (or multi-word with a CMU miss): original path.
    single_norm = norm_parts[0] if len(parts) == 1 else "".join(norm_parts)
    ipa, arpa, cats = transcribe_word(single_norm)
    if ipa:
        return PronounceResponse(
            word=raw, normalized=single_norm, ipa=ipa,
            arpabet=arpa, categories=cats, source="cmu",
        )

    # CMU miss → Wiktionary (GA IPA) → Claude fallback.
    wik_ipa = await wiktionary_ipa.lookup(raw if len(parts) == 1 else single_norm)
    if wik_ipa:
        return PronounceResponse(
            word=raw, normalized=single_norm, ipa=wik_ipa,
            arpabet=[], categories=classify_ipa(wik_ipa), source="wiktionary",
        )
    llm_map = await llm_transcribe_words([single_norm])
    llm_ipa = llm_map.get(single_norm)
    return PronounceResponse(
        word=raw, normalized=single_norm, ipa=llm_ipa,
        arpabet=[], categories=classify_ipa(llm_ipa),
        source="llm" if llm_ipa else "none",
    )


@api_router.post("/scenes/upload", response_model=Scene)
async def upload_scene(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = None,
):
    # Gate: subscribers unlimited; trial users get 1 scene upload.
    actor = await require_access(request, db, kind="scene")

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

    # Quota safety net: pre-cache Real Speaker caption search for every
    # proper noun in the scene. Runs in the background so the upload
    # response is instant. Proper nouns (names, cities) are the words
    # students are most likely to look up.
    if proper_nouns:
        background_tasks.add_task(_prewarm_proper_nouns, proper_nouns)

    await consume_trial(db, actor)
    return Scene(**doc)


async def _prewarm_proper_nouns(words: List[str]) -> None:
    """Warm the caption_search_cache for the scene's proper nouns. Runs
    serially with a short delay to be gentle on the YouTube API quota.
    Silently skips already-cached words and any that fail (rate limits,
    etc) — those simply mean the student's first click will do the work."""
    unique = list({w.strip() for w in words if w and w.strip()})
    unique.sort()
    for word in unique:
        try:
            await caption_service.search(word, limit=6)
        except Exception as exc:  # noqa: BLE001
            logger.debug("prewarm caption failed for %r: %s", word, exc)
            continue
        await asyncio.sleep(0.5)


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


def _refresh_categories(doc: Dict) -> Dict:
    """Recompute sound categories so scenes saved under an older category
    scheme pick up the current laundry-list definitions."""
    for t in doc.get("tokens", []):
        if not t.get("is_word"):
            continue
        if t.get("source", "cmu") == "cmu":
            phones = get_arpabet(normalize_word(t["text"]))
            if phones:
                t["arpabet"] = phones
                t["ipa"] = arpabet_to_ipa(phones)
        if t.get("arpabet"):
            t["categories"] = classify_word(t["arpabet"])
        elif t.get("ipa"):
            t["categories"] = classify_ipa(t["ipa"])
    return doc


@api_router.get("/scenes/{scene_id}", response_model=Scene)
async def get_scene(scene_id: str):
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")
    doc = _refresh_categories(await _ensure_dialogue_only(doc))
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
    doc = _refresh_categories(doc)

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
                "is_proper_noun": bool(t.get("is_proper_noun")),
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


TTS_VERSION = 2  # bump when synthesis settings change so cached audio regenerates


def _phoneme_markup(text: str) -> str:
    """Wrap each dictionary word in a CMU-Arpabet <phoneme> tag."""
    def _wrap(m: re.Match) -> str:
        w = m.group(0)
        phones = get_arpabet(w)
        if not phones:
            return w
        return f'<phoneme alphabet="cmu-arpabet" ph="{" ".join(phones)}">{w}</phoneme>'
    return re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", _wrap, text)


@api_router.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest, request: Request):
    word = (req.word or "").strip()
    if not word:
        raise HTTPException(status_code=400, detail="word is required")

    # Gate: subscribers unlimited; trial users get 1 word audio.
    actor = await require_access(request, db, kind="word")

    base_key = word.lower()
    # Coach-preferred pronunciations must be audible, not just displayed.
    if normalize_word(word) in PREFERRED_ARPA:
        req.phonetic = True
    # Manual overrides always win, regardless of mode.
    override = await db.audio_cache.find_one(
        {"word": base_key, "manual_override": True}, {"_id": 0})
    cache_key = f"{base_key}#ph" if req.phonetic else base_key
    cached = override or await db.audio_cache.find_one({"word": cache_key}, {"_id": 0})
    # Plain entries: accept legacy (no version) or current; reject the
    # short-lived v2 turbo renders that sounded off on common words.
    ok_version = (cached or {}).get("tts_version") != 2
    if cached and cached.get("audio_b64") and (
        cached.get("manual_override") or (ok_version if not req.phonetic
                                          else cached.get("tts_version") == TTS_VERSION)
    ):
        await consume_trial(db, actor)
        return TTSResponse(
            word=word,
            audio_b64=cached["audio_b64"],
            cached=True,
            manual_override=bool(cached.get("manual_override")),
        )

    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    def _generate() -> bytes:
        client = _eleven_client()
        # Proper nouns: CMU Arpabet phoneme tags on eleven_turbo_v2 so names
        # like "Harry" are said exactly as the IPA shown on screen.
        # Ordinary words: plain multilingual_v2 (original engine).
        # A trailing period cues a declarative (falling-pitch) reading.
        spoken = _phoneme_markup(word) if req.phonetic else word
        if not spoken.endswith((".", "!", "?")):
            spoken += "."
        stream = client.text_to_speech.convert(
            text=spoken,
            voice_id=voice_id,
            model_id="eleven_turbo_v2" if req.phonetic else "eleven_multilingual_v2",
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
                      "tts_version": TTS_VERSION if req.phonetic else 3,
                      "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    await consume_trial(db, actor)
    return TTSResponse(word=word, audio_b64=audio_b64, cached=False)


def _preferred_markup(text: str) -> tuple:
    """Wrap coach-preferred words in phoneme tags. Returns (text, changed)."""
    changed = False

    def _wrap(m: re.Match) -> str:
        nonlocal changed
        w = m.group(0)
        arp = PREFERRED_ARPA.get(w.lower())
        if not arp:
            return w
        changed = True
        return f'<phoneme alphabet="cmu-arpabet" ph="{arp}">{w}</phoneme>'
    return re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", _wrap, text), changed


def _synthesize(text: str, voice_id: Optional[str] = None) -> bytes:
    """Blocking ElevenLabs synthesis for an arbitrary line of text.

    Lines containing a coach-preferred word are rendered on eleven_turbo_v2
    with phoneme tags so the line follows the chosen pronunciation; all
    other lines keep the original multilingual voice."""
    client = _eleven_client()
    vid = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    spoken, tagged = _preferred_markup(text)
    stream = client.text_to_speech.convert(
        text=spoken,
        voice_id=vid,
        model_id="eleven_turbo_v2" if tagged else "eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    buf = bytearray()
    for chunk in stream:
        if chunk:
            buf.extend(chunk)
    return bytes(buf)


# --- Caption search (YouGlish replacement) ---------------------------------
async def suggest_spelling(q: str) -> Optional[str]:
    """Return a corrected spelling for a likely-misspelled word/name, or None."""
    if not llm.is_configured() or len(q) > 60:
        return None
    system = (
        "An actor typed a single English word, character name, or US place "
        "name, possibly misspelled. Reply with ONLY the most likely intended "
        "correct spelling, preserving capitalization conventions (e.g. "
        "'Charlston' -> 'Charleston', 'Hermione' -> 'Hermione'). If it is "
        "already correct or you are unsure, reply with the input unchanged."
    )
    raw = await llm.complete(system, q, max_tokens=20)
    if not raw:
        return None
    fixed = raw.strip().strip('"\'.').split("\n")[0].strip()
    if not fixed or fixed.lower() == q.lower() or len(fixed) > 60:
        return None
    return fixed


@api_router.get("/caption-search")
async def caption_search(q: str, limit: int = 6, refresh: bool = False):
    """Search curated American-speaker YouTube channels for videos where the
    given word/phrase is actually spoken in the captions."""
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Missing query.")
    if len(q) > 80:
        raise HTTPException(status_code=400, detail="Query too long.")
    limit = max(1, min(limit, 10))
    result = await caption_service.search(q, limit=limit, force_refresh=refresh)
    if not result.get("results") and not result.get("error"):
        # Likely a typo ("Charlston") — retry with the corrected spelling.
        fixed = await suggest_spelling(q)
        if fixed:
            retry = await caption_service.search(fixed, limit=limit,
                                                 force_refresh=refresh)
            if retry.get("results"):
                retry["corrected_query"] = fixed
                retry["query"] = q
                return retry
    return result


@api_router.get("/scenes/{scene_id}/download-lines")
async def download_my_lines(
    request: Request,
    scene_id: str,
    character: str,
    voice: Optional[str] = None,
    gap_ms: int = 2000,
):
    # Bundled-MP3 download is a subscriber perk.
    await require_subscriber(request, db)
    """Return a single MP3 containing every one of `character`'s lines
    concatenated with a short silent gap between them (default 2s — the
    beat where the other character would speak). Reuses turn_audio_cache
    so a scene the actor has already played back downloads instantly.
    """
    from pydub import AudioSegment

    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")
    doc = await _ensure_dialogue_only(doc)

    voice_id: Optional[str] = None
    voice_key: Optional[str] = None
    if voice:
        voice_key = voice.lower().strip()
        if voice_key not in READER_VOICES:
            raise HTTPException(status_code=400, detail="Unknown voice.")
        voice_id = READER_VOICES[voice_key]

    turns = doc.get("turns") or []
    normalized_char = (character or "").strip()
    mine = [t for t in turns if (t.get("speaker") or "").strip() == normalized_char]
    if not mine:
        raise HTTPException(
            status_code=404,
            detail=f"No lines found for character '{character}'.",
        )

    gap_ms = max(0, min(int(gap_ms), 10000))
    gap = AudioSegment.silent(duration=gap_ms) if gap_ms > 0 else None

    # Fetch (or generate + cache) each line's audio, then concatenate.
    combined: Optional[AudioSegment] = None
    for turn in mine:
        turn_idx = turn.get("index", 0)
        cache_key = (
            f"{scene_id}:{turn_idx}"
            + (f":{voice_key}" if voice_key else "")
        )
        cached = await db.turn_audio_cache.find_one(
            {"key": cache_key}, {"_id": 0},
        )
        if cached and cached.get("audio_b64"):
            audio_bytes = base64.b64decode(cached["audio_b64"])
        else:
            try:
                audio_bytes = await asyncio.to_thread(
                    _synthesize, turn["text"], voice_id,
                )
            except Exception as e:
                logger.exception("Download lines TTS error")
                raise HTTPException(
                    status_code=502, detail=f"TTS failed: {e}",
                )
            if audio_bytes:
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                async with _tts_lock:
                    await db.turn_audio_cache.update_one(
                        {"key": cache_key},
                        {"$set": {
                            "key": cache_key,
                            "text": turn["text"],
                            "audio_b64": audio_b64,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }},
                        upsert=True,
                    )
        if not audio_bytes:
            continue
        try:
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        except Exception:
            logger.exception("Failed to decode line MP3 for concat")
            continue
        if combined is None:
            combined = seg
        else:
            combined = combined + gap + seg if gap is not None else combined + seg

    if combined is None:
        raise HTTPException(status_code=502, detail="No audio to bundle.")

    out = io.BytesIO()
    await asyncio.to_thread(
        combined.export, out, format="mp3", bitrate="128k",
    )
    out.seek(0)
    audio_bytes = out.getvalue()

    safe_char = re.sub(r"[^A-Za-z0-9]+", "-", normalized_char).strip("-") or "lines"
    scene_slug = re.sub(r"[^A-Za-z0-9]+", "-", doc.get("title", "scene")).strip("-") or "scene"
    filename = f"{scene_slug}_{safe_char}.mp3"
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Reader voices for "Run Lines" mode ------------------------------------
# Whitelist of voices coaches can pick as the scene-partner voice. Keeps the
# server in charge of which voices are permissible (never trust an arbitrary
# id from the client) and gives us stable IDs the frontend can display.
READER_VOICES = {
    "jessica": "r1KmysJdVYZjJCm4mL3b",  # female US
    "adam":    "pNInz6obpgDQGcFmaJgB",  # male US
}

READER_VOICE_META = [
    {"key": "jessica", "label": "Jessica", "gender": "female",
     "description": "American English, warm, natural"},
    {"key": "adam",    "label": "Adam",    "gender": "male",
     "description": "American English, deep, natural"},
]


@api_router.get("/reader-voices")
async def list_reader_voices():
    """Which voices the Run Lines partner can use. Voice IDs live server-side."""
    return {"voices": READER_VOICE_META}


@api_router.post("/scenes/{scene_id}/turns/{turn_index}/tts",
                 response_model=TurnTTSResponse)
async def tts_turn(scene_id: str, turn_index: int, voice: Optional[str] = None):
    """Generate (and cache) audio for one continuous speaker turn.

    `voice` is an optional key from READER_VOICES (e.g. "jessica" or "adam")
    used by the Run Lines mode to synthesize other characters in a different
    voice. Cache is keyed per (scene, turn, voice) so switching voices only
    costs a fresh synthesis for the new voice — previous voices stay warm.
    """
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")
    doc = await _ensure_dialogue_only(doc)

    turns = doc.get("turns") or []
    if turn_index < 0 or turn_index >= len(turns):
        raise HTTPException(status_code=404, detail="Turn not found")
    turn = turns[turn_index]

    voice_id: Optional[str] = None
    voice_key: Optional[str] = None
    if voice:
        voice_key = voice.lower().strip()
        if voice_key not in READER_VOICES:
            raise HTTPException(status_code=400, detail="Unknown voice.")
        voice_id = READER_VOICES[voice_key]

    cache_key = f"{scene_id}:{turn_index}" + (f":{voice_key}" if voice_key else "")
    cached = await db.turn_audio_cache.find_one({"key": cache_key}, {"_id": 0})
    if cached and cached.get("audio_b64"):
        return TurnTTSResponse(
            scene_id=scene_id, turn_index=turn_index,
            speaker=turn.get("speaker"), audio_b64=cached["audio_b64"],
            cached=True,
        )

    try:
        audio_bytes = await asyncio.to_thread(_synthesize, turn["text"], voice_id)
    except Exception as e:
        logger.exception("ElevenLabs turn TTS error")
        raise HTTPException(status_code=502, detail=f"TTS failed: {e}")

    if not audio_bytes:
        raise HTTPException(status_code=502, detail="TTS returned empty audio")

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    async with _tts_lock:
        await db.turn_audio_cache.update_one(
            {"key": cache_key},
            {"$set": {"key": cache_key, "scene_id": scene_id, "text": turn["text"],
                      "turn_index": turn_index, "audio_b64": audio_b64,
                      "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return TurnTTSResponse(
        scene_id=scene_id, turn_index=turn_index,
        speaker=turn.get("speaker"), audio_b64=audio_b64, cached=False,
    )


# --- Mount ------------------------------------------------------------------
api_router.include_router(create_auth_router(db))
api_router.include_router(create_kajabi_router(db))
api_router.include_router(create_admin_router(db))
api_router.include_router(create_stripe_router(db))
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup_indexes():
    await ensure_auth_indexes(db)
    async for pref in db.pronunciation_prefs.find({}, {"_id": 0}):
        PREFERRED_ARPA[pref["word"]] = pref["arpabet"]
    # Ensure the caption_transcript_cache text index exists so the local
    # word-in-caption search works. Idempotent.
    try:
        await caption_service.ensure_local_indexes()
    except Exception as exc:
        logger.warning("caption local index bootstrap failed: %s", exc)

    # Auto-kick channel ingest on cold start IF the transcript cache is
    # nearly empty, AND run a weekly refresh forever after so new uploads
    # keep flowing in. Runs in the background — doesn't block startup.
    # Idempotent: if another instance already started it, the job row will
    # be marked running and this will short-circuit.
    WEEKLY_INTERVAL_SECONDS = 7 * 24 * 3600     # 7 days
    DAILY_CHECK_SECONDS = 24 * 3600             # check every 24h

    async def _run_full_ingest() -> None:
        """One pass over all curated channels. Non-overlapping."""
        status = await db.ingest_status.find_one(
            {"job": "channels"}, {"_id": 0}
        )
        if status and status.get("running"):
            return
        try:
            await db.ingest_status.update_one(
                {"job": "channels"},
                {"$set": {
                    "job": "channels",
                    "running": True,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "channels_done": 0,
                    "channels_total": 0,
                    "totals": {"ingested": 0, "skipped": 0, "failed": 0},
                }},
                upsert=True,
            )
            ch_ids = await caption_service._get_curated_channel_ids()
            await db.ingest_status.update_one(
                {"job": "channels"},
                {"$set": {"channels_total": len(ch_ids)}},
            )
            totals = {"ingested": 0, "skipped": 0, "failed": 0}
            for i, cid in enumerate(ch_ids, start=1):
                r = await caption_service.ingest_channel_videos(
                    cid, per_channel_limit=200
                )
                for k in totals:
                    totals[k] = totals.get(k, 0) + int(r.get(k, 0) or 0)
                await db.ingest_status.update_one(
                    {"job": "channels"},
                    {"$set": {
                        "channels_done": i,
                        "last_channel": cid,
                        "totals": totals,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
        finally:
            await db.ingest_status.update_one(
                {"job": "channels"},
                {"$set": {
                    "running": False,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "last_full_finished_at": datetime.now(timezone.utc).isoformat(),
                }},
            )

    async def _ingest_supervisor():
        """Runs forever. On boot: if cache is thin, ingest right away.
        Then every 24h: if last full ingest was > 7 days ago, run again.
        """
        try:
            await asyncio.sleep(20)  # let pod finish booting
            indexed = await db.caption_transcript_cache.count_documents(
                {"has_transcript": True}
            )
            if indexed < 200:
                logger.info(
                    "ingest supervisor: cold-start ingest (indexed=%d)", indexed
                )
                try:
                    await _run_full_ingest()
                except Exception as exc:
                    logger.warning("cold-start ingest failed: %s", exc)

            # Weekly refresh loop.
            while True:
                await asyncio.sleep(DAILY_CHECK_SECONDS)
                try:
                    status = await db.ingest_status.find_one(
                        {"job": "channels"}, {"_id": 0}
                    )
                    last_finished = (status or {}).get("last_full_finished_at")
                    now = datetime.now(timezone.utc)
                    due = True
                    if last_finished:
                        try:
                            last_dt = datetime.fromisoformat(
                                last_finished.replace("Z", "+00:00")
                            )
                            due = (now - last_dt).total_seconds() >= WEEKLY_INTERVAL_SECONDS
                        except Exception:
                            due = True
                    if due:
                        logger.info("ingest supervisor: weekly refresh due")
                        try:
                            await _run_full_ingest()
                        except Exception as exc:
                            logger.warning(
                                "weekly refresh ingest failed: %s", exc
                            )
                except Exception as exc:
                    logger.warning("ingest supervisor tick failed: %s", exc)
        except asyncio.CancelledError:
            return

    asyncio.create_task(_ingest_supervisor())


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
