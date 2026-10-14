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
from datetime import date, datetime, timedelta, timezone
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
    CUSTOM_IPA,
    PREFERRED_ARPA,
    SOUND_CATEGORIES,
    arpabet_to_ipa,
    arpabet_to_respelling,
    classify_ipa,
    classify_word,
    custom_phrases,
    get_arpabet,
    heteronym_variants,
    ipa_to_arpabet,
    phrase_ipa_parts,
    respell_arpabet,
    transcribe_word,
    validate_arpabet,
)
from caption_search import CaptionSearchService
from notify import notify_owner
import notify
import line_check
from word_check import judge_word
import page_allowance
from wiktionary import WiktionaryIPA
import llm
from auth import (
    create_auth_router,
    require_access,
    require_login,
    require_subscriber,
    optional_login,
    is_admin_email,
    rate_limit,
    client_ip,
    consume_trial,
    backfill_email_keys,
    ensure_indexes as ensure_auth_indexes,
)
from kajabi import create_kajabi_router
from admin import create_admin_router
from dictionary import create_dictionary_router, load_custom_ipa, revoice_recording, seed_toponyms
from stripe_payments import create_stripe_router

# --- DB ---------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]
notify.set_db(db)

# --- App --------------------------------------------------------------------
app = FastAPI(title="Pronounce This")


@app.middleware("http")
async def _close_connections(request: Request, call_next):
    # Production sits behind a load balancer + Cloudflare. Idle keep-alive
    # connections that uvicorn closes (5s) while the LB still reuses them
    # surface to users as Cloudflare 520s. Closing per response removes the race.
    response = await call_next(request)
    response.headers["Connection"] = "close"
    return response
api_router = APIRouter(prefix="/api")

caption_service = CaptionSearchService(db)
wiktionary_ipa = WiktionaryIPA(db)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MAX_SCENE_PAGES = page_allowance.MEMBER_PAGE_CAP
TRIAL_MAX_SCENE_PAGES = 2
MS_PER_SPOKEN_WORD = 420  # ~140 wpm conversational pace, used to size reader-track gaps
SCENE_RETENTION_DAYS = 90


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
    # Heteronyms resolved in sentence context ("Noun" / "Verb" …). When set,
    # `arpabet` is the context-correct variant and must not be recomputed.
    variant_label: Optional[str] = None


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
    owner_email: Optional[str] = None   # None only for legacy (pre-ownership) scenes
    legacy: bool = False


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
    # Explicit CMU ARPABET ("P R OW1 D UW0 S") for heteronym variants.
    arpabet: Optional[str] = None


class TTSResponse(BaseModel):
    word: str
    audio_b64: str  # raw base64 (no data: prefix)
    mime: str = "audio/mpeg"
    cached: bool = False
    # True when this audio came from an admin-uploaded manual pronunciation
    # override rather than ElevenLabs. The frontend uses this to decide
    # whether to also nudge the user toward Real Speakers.
    manual_override: bool = False


class PronunciationVariant(BaseModel):
    label: str
    gloss: str = ""
    ipa: str
    arpabet: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)


class PronounceResponse(BaseModel):
    """Result of a single-word IPA lookup (no audio)."""
    word: str
    normalized: str
    ipa: Optional[str]
    arpabet: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    source: str  # "cmu" | "llm" | "none"
    # Heteronyms (PRO-duce vs pro-DUCE): one entry per part of speech.
    variants: List[PronunciationVariant] = Field(default_factory=list)


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


def _repair_truncated_json(text: str) -> Optional[dict]:
    """Salvage a JSON object whose output was cut off mid-array: keep every
    complete {...} item in "dialogue" and close the structure."""
    start = text.find('"dialogue"')
    if start < 0:
        return None
    arr = text.find("[", start)
    if arr < 0:
        return None
    items, depth, item_start = [], 0, None
    i = arr + 1
    in_str = False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                item_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and item_start is not None:
                try:
                    items.append(json.loads(text[item_start:i + 1]))
                except Exception:
                    pass
                item_start = None
        elif ch == "]" and depth == 0:
            break
        i += 1
    if not items:
        return None
    return {"dialogue": items, "proper_nouns": []}


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
    # Long scripts need room: a 10-page scene is ~6-8k output tokens.
    raw = await llm.complete(system, raw_text, max_tokens=16000)
    if raw is None:
        return None

    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned,
                     flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
    except Exception:
        data = _repair_truncated_json(cleaned)
        if data is None:
            logger.warning("LLM dialogue parse failed :: %s", cleaned[:200])
            return None
        logger.warning("LLM dialogue JSON was truncated; salvaged %d lines",
                       len(data.get("dialogue") or []))
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
        if llm_out is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Our script reader is temporarily unavailable, so this PDF "
                    "couldn't be parsed. Please try again in a few minutes."
                ),
            )
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
    await _resolve_heteronyms_in_context(tokens, dialogue)
    return tokens, turns_public, dialogue, proper_nouns


_NOUN_CUES = {"a", "an", "the", "this", "that", "these", "those", "my", "your",
              "his", "her", "our", "their", "its", "some", "any", "each",
              "every", "no", "of", "for", "with", "on", "in", "at", "from"}
_VERB_CUES = {"to", "will", "would", "can", "could", "should", "may", "might",
              "must", "shall", "i", "we", "they", "you", "don't", "didn't",
              "doesn't", "won't", "can't", "let's", "please", "just", "gonna"}


def _heteronym_guess(prev_word: str, variants: List[Dict]) -> Dict:
    """Dictionary-free fallback: pick by the word before it."""
    labels = [v["label"].lower() for v in variants]
    want = None
    if prev_word in _NOUN_CUES:
        want = "noun"
    elif prev_word in _VERB_CUES:
        want = "verb"
    if want:
        for v, lab in zip(variants, labels):
            if want in lab:
                return v
    return variants[0]


async def _resolve_heteronyms_in_context(tokens: List[WordToken],
                                         dialogue: List[Dict]) -> None:
    """Words like record / produce / present change pronunciation with part
    of speech. Ask the LLM which reading each occurrence takes in its line;
    fall back to a neighbouring-word heuristic when the LLM is unavailable."""
    line_text = {d["index"]: d["text"] for d in dialogue}
    hits: List[tuple] = []  # (token_pos, variants)
    for pos, t in enumerate(tokens):
        if not t.is_word:
            continue
        variants = heteronym_variants(normalize_word(t.text))
        if len(variants) > 1:
            hits.append((pos, variants))
    if not hits:
        return

    def prev_word(pos: int) -> str:
        for j in range(pos - 1, -1, -1):
            if tokens[j].is_word:
                return normalize_word(tokens[j].text)
            if tokens[j].text.strip() in {".", "!", "?", "\n\n"}:
                break
        return ""

    choices: Dict[int, str] = {}
    if llm.is_configured():
        items = [
            {"id": i, "word": tokens[pos].text,
             "sentence": line_text.get(tokens[pos].turn_index, ""),
             "options": [v["label"] for v in variants]}
            for i, (pos, variants) in enumerate(hits)
        ]
        system = (
            "You label heteronyms in screenplay dialogue. For each item, decide "
            "how the given word is used in its sentence and answer with exactly "
            "one of the provided options (copy the option text verbatim). "
            "Return ONLY a JSON object mapping each id (as a string) to the "
            "chosen option. No commentary, no markdown."
        )
        raw = await llm.complete(system, json.dumps(items), max_tokens=2048)
        if raw:
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    choices = {int(k): str(v) for k, v in data.items() if str(k).isdigit()}
            except Exception as e:
                logger.warning("heteronym labels parse failed: %s", e)

    for i, (pos, variants) in enumerate(hits):
        picked = None
        label = choices.get(i)
        if label:
            picked = next((v for v in variants if v["label"].lower() == label.lower()), None)
        if picked is None:
            picked = _heteronym_guess(prev_word(pos), variants)
        t = tokens[pos]
        t.arpabet = picked["arpabet"]
        t.ipa = picked["ipa"]
        t.categories = picked["categories"]
        t.variant_label = picked["label"]


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
    return {"message": "Pronounce This API"}


@api_router.get("/health")
async def health():
    return {"ok": True, "tts_version": TTS_VERSION, "tts_model": TTS_MODEL, "voice": DEFAULT_VOICE_ID}


@api_router.get("/sound-categories")
async def sound_categories():
    return {"categories": SOUND_CATEGORIES}


@api_router.get("/pronounce", response_model=PronounceResponse)
async def pronounce(word: str, request: Request):
    rate_limit(f"pron:ip:{client_ip(request)}", 60, 60)
    caller = await optional_login(request, db)
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
    # Trial gate: each distinct word looked up (or heard) counts once.
    actor = await require_access(request, db, kind="word", word=norm)
    await consume_trial(db, actor)

    # Multi-word: a coach entry for the whole phrase ("baton rouge") wins;
    # otherwise per-word CMU lookup and stitch. Fast path — no LLM.
    if len(parts) > 1:
        phrase = CUSTOM_IPA.get(norm)
        if phrase:
            return PronounceResponse(
                word=raw, normalized=norm, ipa=phrase,
                arpabet=ipa_to_arpabet(phrase) or [], categories=classify_ipa(phrase), source="custom",
            )
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
        variants = heteronym_variants(single_norm) if len(parts) == 1 else []
        if variants:
            v0 = variants[0]
            ipa, arpa, cats = v0["ipa"], v0["arpabet"], v0["categories"]
        return PronounceResponse(
            word=raw, normalized=single_norm, ipa=ipa,
            arpabet=arpa, categories=cats, source="cmu",
            variants=[PronunciationVariant(**v) for v in variants],
        )

    # CMU miss → Wiktionary (GA IPA) → Claude fallback.
    wik_ipa = await wiktionary_ipa.lookup(raw if len(parts) == 1 else single_norm)
    if wik_ipa:
        return PronounceResponse(
            word=raw, normalized=single_norm, ipa=wik_ipa,
            arpabet=[], categories=classify_ipa(wik_ipa), source="wiktionary",
        )
    # Claude costs money: only for signed-in users, and metered.
    llm_ipa = None
    if caller:
        rate_limit(f"pron:llm:{caller}", 30, 3600)
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
        page_cap = MAX_SCENE_PAGES if actor.is_subscriber else TRIAL_MAX_SCENE_PAGES
        if len(reader.pages) > page_cap:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This PDF has {len(reader.pages)} pages. Please upload a "
                    f"scene of {page_cap} pages or less."
                    + ("" if actor.is_subscriber else
                       f" Free-trial scenes are limited to {TRIAL_MAX_SCENE_PAGES} pages; members can upload up to {MAX_SCENE_PAGES}.")
                ),
            )
        pages = [(p.extract_text() or "") for p in reader.pages]
        if actor.is_subscriber:
            allowance = await page_allowance.usage(db, actor.email)
            if len(pages) > allowance["remaining"]:
                raise HTTPException(status_code=429, detail=page_allowance.limit_message(allowance, len(pages)))
    except HTTPException:
        raise
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

    scene.owner_email = actor.email
    scene.legacy = False
    doc = scene.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    doc["expires_at_dt"] = datetime.now(timezone.utc) + timedelta(days=SCENE_RETENTION_DAYS)
    doc["dialogue_only"] = True
    doc["dialogue"] = dialogue
    doc["proper_nouns"] = proper_nouns
    await db.scenes.insert_one(doc)
    if actor.is_subscriber:
        await page_allowance.record(db, actor.email, len(pages), scene.id)

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


async def _load_owned_scene(scene_id: str, request: Request) -> Dict:
    """Fetch a scene the caller may access: its owner, or an admin.
    Legacy (unowned) scenes are admin-only. 404s hide existence from others."""
    email = await require_login(request, db)
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scene not found")
    if doc.get("owner_email") != email and not is_admin_email(email):
        raise HTTPException(status_code=404, detail="Scene not found")
    return doc


@api_router.get("/scenes", response_model=List[SceneSummary])
async def list_scenes(request: Request):
    email = await require_login(request, db)
    cursor = db.scenes.find({"owner_email": email},
                            {"_id": 0, "id": 1, "title": 1, "tokens": 1, "created_at": 1})
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


def _apply_phrase_overrides(tokens: List[Dict]) -> set:
    """Place names the coach entered as phrases ("baton rouge") override the
    per-word IPA of consecutive tokens. Returns the token ids handled."""
    done: set = set()
    phrases = custom_phrases()
    if not phrases:
        return done
    words = [(i, normalize_word(t["text"])) for i, t in enumerate(tokens) if t.get("is_word")]
    for p in phrases:
        pieces = phrase_ipa_parts(p)
        if not pieces:
            continue
        keys = p.split()
        n = len(keys)
        for s in range(len(words) - n + 1):
            if any(words[s + j][0] in done for j in range(n)):
                continue
            if [words[s + j][1] for j in range(n)] == keys:
                for j in range(n):
                    idx = words[s + j][0]
                    tokens[idx]["ipa"] = pieces[j]
                    tokens[idx]["categories"] = classify_ipa(pieces[j])
                    tokens[idx]["source"] = "custom"
                    done.add(idx)
    return done


def _refresh_categories(doc: Dict) -> Dict:
    """Recompute sound categories so scenes saved under an older category
    scheme pick up the current laundry-list definitions."""
    tokens = doc.get("tokens", [])
    handled = _apply_phrase_overrides(tokens)
    for i, t in enumerate(tokens):
        if not t.get("is_word") or i in handled:
            continue
        key = normalize_word(t["text"])
        if t.get("variant_label") and t.get("arpabet"):
            t["ipa"] = arpabet_to_ipa(t["arpabet"])
            t["categories"] = classify_word(t["arpabet"])
            continue
        if t.get("source", "cmu") == "cmu":
            phones = get_arpabet(key)
            if phones:
                t["arpabet"] = phones
                t["ipa"] = arpabet_to_ipa(phones)
        if key in CUSTOM_IPA:
            t["ipa"] = CUSTOM_IPA[key]
            t["categories"] = classify_ipa(t["ipa"])
            continue
        if t.get("arpabet"):
            t["categories"] = classify_word(t["arpabet"])
        elif t.get("ipa"):
            t["categories"] = classify_ipa(t["ipa"])
    return doc


@api_router.get("/scenes/{scene_id}", response_model=Scene)
async def get_scene(scene_id: str, request: Request):
    doc = await _load_owned_scene(scene_id, request)
    doc = _refresh_categories(await _ensure_dialogue_only(doc))
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    return Scene(**doc)


@api_router.post("/scenes/{scene_id}/reparse", response_model=Scene)
async def reparse_scene(scene_id: str, request: Request):
    """Force a re-extraction of dialogue for a saved scene. Useful if the
    original extraction missed lines or grouped them oddly."""
    doc = await _load_owned_scene(scene_id, request)
    doc["dialogue_only"] = False  # Force re-run.
    doc = await _ensure_dialogue_only(doc)
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    return Scene(**doc)


@api_router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str, request: Request):
    await _load_owned_scene(scene_id, request)
    res = await db.scenes.delete_one({"id": scene_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Scene not found")
    return {"ok": True}


@api_router.get("/scenes/{scene_id}/laundry-list")
async def laundry_list(scene_id: str, sound: str, request: Request):
    doc = _refresh_categories(await _load_owned_scene(scene_id, request))

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
    return ElevenLabs(api_key=api_key, timeout=60)


# Retry transient ElevenLabs failures (429 / 5xx / timeouts) inside the SDK.
ELEVEN_REQUEST_OPTIONS = {"max_retries": 3, "timeout_in_seconds": 60}


TTS_VERSION = 5  # bump when synthesis settings change so cached audio regenerates
# Unspoken context around a single word so v4 reads it as American English.
WORD_CONTEXT_BEFORE = "You're an American English coach from the Midwest speaking in your natural General American accent. Listen and repeat after me. The word is"
WORD_CONTEXT_BEFORE_STRONG = "You're an American English coach from the Midwest speaking in your natural General American accent. Listen and repeat after me, slowly and clearly. The English word is"
WORD_CONTEXT_AFTER = "That's how we say it in American English. Now you try."
# Default ElevenLabs voice for single words + untargeted lines (Hannah).
DEFAULT_VOICE_ID = "ZSNL4hPqCnqoMPaI4jGX"


def _render_word_text(spoken: str, prev: str = WORD_CONTEXT_BEFORE, nxt: str = WORD_CONTEXT_AFTER) -> bytes:
    """Blocking single-word render on the current voice/model."""
    stream = _eleven_client().text_to_speech.convert(
        text=spoken, voice_id=DEFAULT_VOICE_ID, model_id=TTS_MODEL, language_code="en",
        previous_text=prev, next_text=nxt, output_format="mp3_44100_128",
        request_options=ELEVEN_REQUEST_OPTIONS)
    return b"".join(c for c in stream if c)


def word_auditions(word: str) -> list:
    """Several candidate renders of a word so the coach can pick by ear."""
    key = re.sub(r"\s+", " ", word.lower().strip())
    coach = CUSTOM_IPA.get(key)
    cmu = " ".join(filter(None, (arpabet_to_ipa(get_arpabet(p)) if get_arpabet(p) else "" for p in key.split()))) or None
    ipa = coach or cmu
    phones = ipa_to_arpabet(ipa) if ipa else None
    respelled = None
    if ipa:
        parts = [respell_arpabet(ipa_to_arpabet(piece) or []) for piece in ipa.split()]
        respelled = " ".join(p for p in parts if p) or None
    cands = [("plain", "Plain spelling", f" {word.strip()}.")]
    if ipa:
        cands.append(("ipa", f"{'Your' if coach else 'Dictionary'} IPA /{_tts_ipa(ipa)}/", f" /{_tts_ipa(ipa)}/."))
    if respelled and respelled.lower() != key:
        cands.append(("respell", f"Respelled “{respelled}”", f" {respelled}."))
    cands.append(("plain_slow", "Plain spelling, slow and clear", f" {word.strip()}."))
    out = []
    for cid, label, spoken in cands:
        prev = WORD_CONTEXT_BEFORE_STRONG if cid == "plain_slow" else WORD_CONTEXT_BEFORE
        try:
            audio = _render_word_text(spoken, prev)
        except Exception as exc:  # noqa: BLE001
            logger.warning("audition %s for %r failed: %s", cid, word, exc)
            continue
        out.append({"id": cid, "label": label, "spoken": spoken.strip(), "audio_b64": base64.b64encode(audio).decode("ascii"),
                    "phones": phones})
    return out


def _tts_ipa(ipa: str) -> str:
    """IPA as ElevenLabs expects it: no display-only syllable dots or slashes."""
    return re.sub(r"[·.]", "", ipa).strip("/ ").strip()


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
    actor = await require_access(request, db, kind="word", word=word)

    base_key = word.lower()
    # Explicit phonemes (heteronym variants) always synthesize phonetically
    # and cache under their own key; manual overrides don't apply to them.
    variant_phones = validate_arpabet(req.arpabet) if req.arpabet else None
    if req.arpabet and not variant_phones:
        raise HTTPException(status_code=400, detail="invalid_arpabet")
    if variant_phones:
        req.phonetic = True
    # Coach-preferred pronunciations must be audible, not just displayed.
    if normalize_word(word) in PREFERRED_ARPA:
        req.phonetic = True
    # Manual overrides always win, regardless of mode.
    override = None if variant_phones else await db.audio_cache.find_one(
        {"word": base_key, "manual_override": True}, {"_id": 0})
    if variant_phones:
        cache_key = f"{base_key}#{'_'.join(variant_phones)}"
    else:
        cache_key = f"{base_key}#ph" if req.phonetic else base_key
    cached = override or await db.audio_cache.find_one({"word": cache_key}, {"_id": 0})
    # Only renders made with the current word pipeline are reused.
    same_voice = (cached or {}).get("voice_id") == DEFAULT_VOICE_ID and \
        (cached or {}).get("model") == TTS_MODEL
    if cached and cached.get("audio_b64") and (
        cached.get("manual_override") or (same_voice and cached.get("tts_version") == TTS_VERSION)
    ):
        await consume_trial(db, actor)
        if not cached.get("manual_override"):
            await _log_tts_play(base_key, req.phonetic)
        return TTSResponse(
            word=word,
            audio_b64=cached["audio_b64"],
            mime=cached.get("content_type") or "audio/mpeg",
            cached=True,
            manual_override=bool(cached.get("manual_override")),
        )

    voice_id = DEFAULT_VOICE_ID
    coach_ipa = CUSTOM_IPA.get(re.sub(r"\s+", " ", word.lower().strip()))
    dict_ipa = coach_ipa or (arpabet_to_ipa(get_arpabet(word)) if get_arpabet(word) else None)

    def _generate(take: int) -> tuple[bytes, Optional[str]]:
        client = _eleven_client()
        # Eleven v4 guesses the language of a bare word (and read "I" as a
        # numeral), so every word is voiced as the tail of an unspoken
        # English sentence (previous/next text are context only, not audio).
        # Take 1: coach entries (My Dictionary, incl. phrases like "Baton
        # Rouge") and overrides as inline IPA, everything else plain
        # spelling. Take 2 (after a failed listen-back) flips the strategy.
        ipa = None
        if variant_phones:
            ipa = arpabet_to_ipa(variant_phones)
        elif coach_ipa or req.phonetic:
            ipa = dict_ipa
        if take > 1 and not variant_phones and not coach_ipa:
            ipa = None if ipa else dict_ipa
        spoken = f" /{_tts_ipa(ipa)}/." if ipa else f" {word}."
        stream = client.text_to_speech.convert(
            text=spoken,
            voice_id=voice_id,
            model_id=TTS_MODEL,
            language_code="en",
            previous_text=WORD_CONTEXT_BEFORE if take == 1 else WORD_CONTEXT_BEFORE_STRONG,
            next_text=WORD_CONTEXT_AFTER,
            output_format="mp3_44100_128",
            request_options=ELEVEN_REQUEST_OPTIONS,
        )
        buf = bytearray()
        for chunk in stream:
            if chunk:
                buf.extend(chunk)
        return bytes(buf), ipa

    try:
        audio_bytes, used_ipa = await asyncio.to_thread(_generate, 1)
    except Exception as e:
        logger.exception("ElevenLabs TTS error")
        raise HTTPException(status_code=502, detail=f"TTS failed: {e}")

    if not audio_bytes:
        raise HTTPException(status_code=502, detail="TTS returned empty audio")

    # Word Audio QA: an AI listener checks the clip; one retake on failure,
    # then the word is flagged for the coach's Recording Queue.
    verdict = await judge_word(audio_bytes, word, used_ipa or dict_ipa)
    takes = 1

    def _heard_ok(v: Optional[dict]) -> bool:
        # A coach-entered pronunciation is deliberate: if the listener heard
        # the right word, don't second-guess her accent/stress choice.
        return bool(v and coach_ipa and re.sub(r"[^a-z]", "", (v.get("heard") or "").lower())
                    == re.sub(r"[^a-z]", "", word.lower()))

    if verdict and not verdict["ok"] and _heard_ok(verdict):
        verdict = {**verdict, "ok": True, "note": "Coach pronunciation; listener heard the word. " + (verdict.get("note") or "")}
    if verdict and not verdict["ok"]:
        try:
            audio2, ipa2 = await asyncio.to_thread(_generate, 2)
            verdict2 = await judge_word(audio2, word, ipa2 or dict_ipa)
            if verdict2 and not verdict2["ok"] and _heard_ok(verdict2):
                verdict2 = {**verdict2, "ok": True, "note": "Coach pronunciation; listener heard the word."}
            takes = 2
            if audio2 and (verdict2 is None or verdict2["ok"] or verdict2["natural"] >= verdict["natural"]):
                audio_bytes, verdict = audio2, (verdict2 or verdict)
        except Exception as exc:  # noqa: BLE001
            logger.warning("word QA retake failed for %s: %s", word, exc)
    flagged = bool(verdict and not verdict["ok"])
    if flagged:
        logger.info("word QA flagged %r: heard %r — %s", word, verdict["heard"], verdict["note"])

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    async with _tts_lock:
        await db.audio_cache.update_one(
            {"word": cache_key},
            {"$set": {"word": cache_key, "audio_b64": audio_b64,
                      "tts_version": TTS_VERSION,
                      "voice_id": DEFAULT_VOICE_ID,
                      "model": TTS_MODEL,
                      "qa": verdict, "takes": takes,
                      "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    await consume_trial(db, actor)
    await _log_tts_play(base_key, req.phonetic, qa=verdict)
    return TTSResponse(word=word, audio_b64=audio_b64, cached=False)


async def _log_tts_play(word: str, phonetic: bool, qa: Optional[dict] = None) -> None:
    """Track synthetic plays so the coach's Recording Queue knows which
    words students actually hear without a human recording."""
    try:
        update = {"$inc": {"count": 1},
                  "$set": {"last_at": datetime.now(timezone.utc).isoformat(),
                           "phonetic": phonetic}}
        if qa is not None:
            update["$set"].update({"qa_flag": not qa["ok"], "qa_heard": qa["heard"],
                                   "qa_note": qa["note"], "qa_natural": qa["natural"]})
            if not qa["ok"]:
                update["$set"]["dismissed"] = False
        await db.tts_log.update_one({"word": word}, update, upsert=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("tts_log write failed: %s", exc)


# Closed-class words are reduced in connected speech; forcing their citation
# form via phoneme tags makes ElevenLabs stumble ("Of course" → "You've course").
_FUNCTION_WORDS = frozenset("""
a an the of to in on at by for from with as and or but nor so yet if than that this
these those there here it its is are was were be been being am do does did have has had
he she they them we you i me him her us my your his our their who whom what which
not no yes up out off over under into onto about just can could will would shall should
may might must
""".split())


def _preferred_markup(text: str, mode: str = "tags") -> tuple:
    """Apply coach pronunciation corrections to a line. Returns (text, uses_tags).
    mode="respell": swap corrected words for a plain-English respelling so the
                    whole line stays on the natural multilingual voice.
    mode="tags":    wrap them in phoneme tags (needs the turbo model).
    mode="plain":   no changes."""
    changed = False
    if mode == "plain":
        return text, False

    # Phrase entries ("baton rouge") first, protected from the word pass.
    held: list = []

    def _hold(repl: str) -> str:
        held.append(repl)
        return f"\x00{len(held) - 1}\x00"

    for p in custom_phrases():
        pat = r"\b" + r"\s+".join(re.escape(k) for k in p.split()) + r"\b"

        def _phrase(m: re.Match, p=p) -> str:
            nonlocal changed
            changed = True
            ipa = CUSTOM_IPA[p]
            if mode == "ipa":
                return _hold(f"/{_tts_ipa(ipa)}/")
            phones = ipa_to_arpabet(ipa)
            if not phones:
                return m.group(0)
            if mode == "respell":
                r = " ".join(respell_arpabet(ipa_to_arpabet(piece) or []) or k
                             for piece, k in zip(ipa.split(), p.split()))
                return _hold(r.title() if m.group(0)[0].isupper() else r)
            return _hold(f'<phoneme alphabet="cmu-arpabet" ph="{" ".join(phones)}">{m.group(0)}</phoneme>')
        text = re.sub(pat, _phrase, text, flags=re.IGNORECASE)

    def _wrap(m: re.Match) -> str:
        nonlocal changed
        w = m.group(0)
        lw = w.lower()
        if lw in _FUNCTION_WORDS:
            return w
        arp = PREFERRED_ARPA.get(lw)
        forced = lw in _ALWAYS_PREFERRED
        custom = CUSTOM_IPA.get(lw)
        if custom:
            # Coach-typed IPA in My Dictionary is a deliberate correction
            # ("oner" → ˈwʌnɚ): it wins and applies in any case.
            phones = ipa_to_arpabet(custom)
            if phones:
                arp, forced = " ".join(phones), True
        if not arp:
            return w
        # Dictionary-migrated words (mostly place names) are only forced when
        # used as a name — capitalised in the line. Lowercase everyday words
        # ("city", "beach") keep the natural multilingual voice.
        if not forced and not w[0].isupper():
            return w
        changed = True
        if mode == "respell":
            r = respell_arpabet(arp.split())
            return (r.capitalize() if w[0].isupper() else r) or w
        if mode == "ipa":                       # Eleven v4 inline IPA
            ipa = custom or arpabet_to_ipa(arp.split())
            return f"/{_tts_ipa(ipa)}/" if ipa else w
        return f'<phoneme alphabet="cmu-arpabet" ph="{arp}">{w}</phoneme>'
    spoken = re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", _wrap, text)
    spoken = re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], spoken)
    return spoken, (changed and mode == "tags")


# Preferences that apply in any case: seeded ones + anything the coach added
# via Admin → Pronunciations (filled at startup; dictionary migrations excluded).
_ALWAYS_PREFERRED: set = {"because"}


# Take order for scene lines on Eleven v4: inline IPA for corrections first
# (same natural voice, no turbo fallback), respelling if listen-back rejects
# it, then plain.
_TAKE_MODES_V4 = ("ipa", "respell", "plain")
TTS_MODEL = "eleven_v4"


def take_mode(n: int) -> str:
    return _TAKE_MODES_V4[min(n, 3) - 1]

_eleven_slots = asyncio.Semaphore(3)  # ElevenLabs plan allows 3 concurrent requests


async def _synth_line(text: str, voice_id: Optional[str] = None, mode: str = "respell") -> bytes:
    """Async, concurrency-capped line synthesis with a short retry when
    ElevenLabs reports concurrent_limit_exceeded."""
    for attempt in range(3):
        async with _eleven_slots:
            try:
                return await asyncio.to_thread(_synthesize, text, voice_id, mode)
            except Exception as exc:  # noqa: BLE001
                if "concurrent_limit_exceeded" in str(exc) and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
    return b""



def _synthesize(text: str, voice_id: Optional[str] = None, mode: str = "respell") -> bytes:
    """Blocking ElevenLabs synthesis for an arbitrary line of text on Eleven v4.
    Coach-preferred words are written as inline IPA so the natural voice
    follows the chosen pronunciation."""
    client = _eleven_client()
    vid = voice_id or DEFAULT_VOICE_ID
    spoken, _ = _preferred_markup(text, mode)
    stream = client.text_to_speech.convert(
        text=spoken,
        voice_id=vid,
        model_id=TTS_MODEL,
        language_code="en",
        output_format="mp3_44100_128",
        request_options=ELEVEN_REQUEST_OPTIONS,
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


class ClipReportBody(BaseModel):
    video_id: str
    reason: str = ""
    query: str = ""


@api_router.post("/cron/onboarding-nudge")
async def cron_onboarding_nudge(request: Request, background_tasks: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    import hmac
    import password_links
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not secret or not token or not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="bad_body")
    run_id = request.headers.get("x-webhook-id") or body.get("run_id") or f"manual-{datetime.now(timezone.utc).isoformat()}"
    dup = await db.cron_runs.find_one({"run_id": run_id}, {"_id": 1})
    if dup:
        return {"ok": True, "duplicate": True}
    await db.cron_runs.insert_one({"run_id": run_id, "job": "onboarding-nudge",
                                   "received_at": datetime.now(timezone.utc).isoformat()})
    background_tasks.add_task(password_links.run_onboarding_nudges, db)
    return {"ok": True, "queued": True, "run_id": run_id}


@api_router.post("/caption-search/report")
async def caption_report(body: ClipReportBody, request: Request):
    """Student flags a clip (offensive, not American, wrong word…). Lands in
    Admin → Reported clips for one-tap hide; the owner is emailed."""
    email = await require_login(request, db)
    rate_limit(f"cap:report:{email}", 20, 3600)
    vid = re.sub(r"[^A-Za-z0-9_-]", "", body.video_id)[:20]
    if not vid:
        raise HTTPException(status_code=400, detail="bad_video_id")
    reason = (body.reason or "").strip()[:120]
    meta = await db.caption_transcript_cache.find_one({"video_id": vid}, {"_id": 0, "channel_meta": 1})
    cm = (meta or {}).get("channel_meta") or {}
    now = datetime.now(timezone.utc).isoformat()
    await db.clip_reports.update_one(
        {"video_id": vid},
        {"$addToSet": {"reporters": email, "reasons": reason} if reason else {"reporters": email},
         "$set": {"status": "open", "last_reason": reason, "query": (body.query or "")[:80],
                  "title": cm.get("title", ""), "channel_title": cm.get("channel_title", ""),
                  "updated_at": now},
         "$setOnInsert": {"video_id": vid, "created_at": now}},
        upsert=True,
    )
    notify_owner("Clip reported", "A member reported a Real Speakers clip",
                 [f"<b>{email}</b> reported <b>{cm.get('title') or vid}</b> ({cm.get('channel_title') or 'unknown channel'}).",
                  f"Reason: {reason or 'not given'}. Word searched: {body.query or '—'}.",
                  "Open Admin → Reported clips to hide or dismiss it."])
    return {"ok": True}


class UnplayableBody(BaseModel):
    video_id: str
    code: int = 0


@api_router.post("/caption-search/unplayable")
async def caption_unplayable(body: UnplayableBody, request: Request):
    """Player reported a clip that will not play (deleted, private, or
    embedding disabled). Player errors can be browser-specific, so a clip is
    only hidden for everyone once two different accounts report it."""
    email = await require_login(request, db)
    rate_limit(f"cap:unplayable:{email}", 60, 3600)
    vid = re.sub(r"[^A-Za-z0-9_-]", "", body.video_id)[:20]
    if not vid:
        raise HTTPException(status_code=400, detail="bad_video_id")
    rep = await db.unplayable_reports.find_one_and_update(
        {"video_id": vid},
        {"$addToSet": {"reporters": email},
         "$set": {"last_code": body.code, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True, return_document=True,
    )
    if len(rep.get("reporters") or []) < 2:
        return {"ok": True, "hidden": False}
    await db.hidden_videos.update_one(
        {"video_id": vid},
        {"$setOnInsert": {"video_id": vid, "reason": f"player_error_{body.code}", "auto": True,
                          "reported_by": email, "channel_title": "", "title": "",
                          "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    await db.caption_transcript_cache.update_many({"video_id": vid}, {"$set": {"embeddable": False}})
    caption_service.invalidate_hidden()
    return {"ok": True, "hidden": True}


@api_router.get("/caption-search")
async def caption_search(q: str, request: Request, limit: int = 6, refresh: bool = False):
    """Search curated American-speaker YouTube channels for videos where the
    given word/phrase is actually spoken in the captions."""
    email = await require_login(request, db)
    rate_limit(f"cap:{email}", 60, 3600)
    if refresh:
        rate_limit(f"cap:refresh:{email}", 10, 3600)
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
    mode: str = "mine",
):
    # Bundled-MP3 download is a subscriber perk.
    await require_subscriber(request, db)
    """mode="mine": every one of `character`'s lines concatenated with a
    short silent gap (default 2s). mode="reader": the *other* characters'
    lines in scene order, with a silent gap where `character` speaks, sized
    to 110% of how long that line takes to say — a rehearsal reader track.
    Reuses turn_audio_cache so an already-played scene downloads instantly.
    """
    from pydub import AudioSegment

    doc = await _load_owned_scene(scene_id, request)
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
    reader_mode = mode == "reader"
    if reader_mode and len(mine) == len(turns):
        raise HTTPException(
            status_code=400,
            detail="This scene has no other character to read against.",
        )

    gap_ms = max(0, min(int(gap_ms), 10000))
    gap = AudioSegment.silent(duration=gap_ms) if gap_ms > 0 else None

    async def turn_segment(turn: Dict) -> Optional[AudioSegment]:
        turn_idx = turn.get("index", 0)
        cache_key = (
            f"{scene_id}:{turn_idx}"
            + (f":{voice_key}" if voice_key else "")
        )
        cached = await db.turn_audio_cache.find_one(
            {"key": cache_key}, {"_id": 0},
        )
        if cached and cached.get("audio_b64") and cached.get("voice_id") == (voice_id or DEFAULT_VOICE_ID) \
                and (cached.get("model") or "eleven_multilingual_v2") == TTS_MODEL:
            audio_bytes = base64.b64decode(cached["audio_b64"])
        else:
            try:
                # Take 1 honours pronunciation preferences; if the listen-back
                # rejects it, the retry renders plain (tags are the usual culprit).
                takes = {"n": 0}

                async def _render():
                    takes["n"] += 1
                    return await _synth_line(turn["text"], voice_id, mode=take_mode(takes["n"]))

                audio_bytes, check = await line_check.render_verified(turn["text"], _render)
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
                            "voice_id": voice_id or DEFAULT_VOICE_ID,
                            "model": TTS_MODEL,
                            "check": check,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }},
                        upsert=True,
                    )
        if not audio_bytes:
            return None
        try:
            return AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        except Exception:
            logger.exception("Failed to decode line MP3 for concat")
            return None

    # Synthesize uncached lines a few at a time so long scenes finish well
    # inside the proxy's request timeout (the frontend also pre-warms).
    sem = asyncio.Semaphore(4)

    async def _bounded(turn: Dict) -> Optional[AudioSegment]:
        async with sem:
            return await turn_segment(turn)

    # Reader mode: my own lines are never heard, so estimate their silence
    # from word count instead of paying ElevenLabs to synthesize them.
    wanted = [t for t in turns if (t.get("speaker") or "").strip() != normalized_char] if reader_mode else mine
    segments = dict(zip(
        [t.get("index", 0) for t in wanted],
        await asyncio.gather(*(_bounded(t) for t in wanted)),
    ))

    combined: Optional[AudioSegment] = None
    if reader_mode:
        # Whole scene in order: partner lines audible, my lines become
        # silence long enough (×1.1) to say them out loud.
        beat = AudioSegment.silent(duration=400)
        for turn in turns:
            is_mine = (turn.get("speaker") or "").strip() == normalized_char
            if is_mine:
                words = len((turn.get("text") or "").split())
                piece = AudioSegment.silent(duration=int(words * MS_PER_SPOKEN_WORD * 1.1))
            else:
                piece = segments.get(turn.get("index", 0))
                if piece is None:
                    continue
            combined = piece if combined is None else combined + beat + piece
    else:
        for turn in mine:
            seg = segments.get(turn.get("index", 0))
            if seg is None:
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
    filename = (
        f"{scene_slug}_readers-lines.mp3" if reader_mode
        else f"{scene_slug}_{safe_char}.mp3"
    )
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
    "jessica": DEFAULT_VOICE_ID,          # Hannah — female US (v4)
    "david":   "c6SfcYrb2t09NHXiT80T",    # Jarnathon — male US (v4-recommended)
}

READER_VOICE_META = [
    {"key": "jessica", "label": "Female voice", "gender": "female",
     "description": "American English, confident, conversational"},
    {"key": "david",   "label": "Male voice",   "gender": "male",
     "description": "American English, warm, natural"},
]


@api_router.get("/reader-voices")
async def list_reader_voices():
    """Which voices the Run Lines partner can use. Voice IDs live server-side."""
    return {"voices": READER_VOICE_META}


@api_router.post("/scenes/{scene_id}/turns/{turn_index}/tts",
                 response_model=TurnTTSResponse)
async def tts_turn(scene_id: str, turn_index: int, request: Request,
                   voice: Optional[str] = None):
    """Generate (and cache) audio for one continuous speaker turn.

    `voice` is an optional key from READER_VOICES (e.g. "jessica" or "adam")
    used by the Run Lines mode to synthesize other characters in a different
    voice. Cache is keyed per (scene, turn, voice) so switching voices only
    costs a fresh synthesis for the new voice — previous voices stay warm.
    """
    doc = await _load_owned_scene(scene_id, request)
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
    if cached and cached.get("audio_b64") and cached.get("voice_id") == (voice_id or DEFAULT_VOICE_ID) \
            and (cached.get("model") or "eleven_multilingual_v2") == TTS_MODEL:
        return TurnTTSResponse(
            scene_id=scene_id, turn_index=turn_index,
            speaker=turn.get("speaker"), audio_b64=cached["audio_b64"],
            cached=True,
        )

    try:
        takes = {"n": 0}

        async def _render():
            takes["n"] += 1
            return await _synth_line(turn["text"], voice_id, mode=take_mode(takes["n"]))

        audio_bytes, check = await line_check.render_verified(turn["text"], _render)
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
                      "voice_id": voice_id or DEFAULT_VOICE_ID,
                      "model": TTS_MODEL,
                      "check": check,
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
api_router.include_router(create_dictionary_router(db))
api_router.include_router(create_stripe_router(db))
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[
        o.strip().rstrip("/") for o in
        (os.environ.get("CORS_ORIGINS") or os.environ["APP_PUBLIC_URL"]).split(",")
        if o.strip() and o.strip() != "*"
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup_indexes():
    await ensure_auth_indexes(db)
    async for pref in db.pronunciation_prefs.find({}, {"_id": 0}):
        PREFERRED_ARPA[pref["word"]] = pref["arpabet"]
        if pref.get("source") != "dictionary":
            _ALWAYS_PREFERRED.add(pref["word"])
    await load_custom_ipa(db)
    try:
        added = await seed_toponyms(db)
        if added:
            logger.info("seeded %d toponym dictionary entries", added)
    except Exception as exc:  # noqa: BLE001
        logger.warning("toponym seed failed: %s", exc)
    # Drop cached scene-line takes the listen-back had flagged as bad so they
    # re-render with the current logic on next play. Idempotent.
    purged = await db.turn_audio_cache.delete_many(
        {"$or": [{"check.gave_up": True}, {"check.stt_bias": True}]})
    if purged.deleted_count:
        logger.info("purged %d flagged scene-line takes from cache", purged.deleted_count)
    # One-time: scene lines containing a coach-corrected dictionary word were
    # rendered before scenes honoured those corrections — drop them once.
    if CUSTOM_IPA and not await db.app_migrations.find_one({"_id": "custom_ipa_scene_lines_v1"}):
        words = [re.escape(w) for w in CUSTOM_IPA if w and " " not in w]
        if words:
            res = await db.turn_audio_cache.delete_many(
                {"text": {"$regex": r"\b(" + "|".join(words) + r")\b", "$options": "i"}})
            logger.info("purged %d scene-line takes containing corrected words", res.deleted_count)
        await db.app_migrations.insert_one({"_id": "custom_ipa_scene_lines_v1", "at": datetime.now(timezone.utc).isoformat()})
    # Human recordings (dictionary builder or the retired "tricky words"
    # uploader) used to be played to members. Convert each to an ElevenLabs
    # phoneme preference and archive the human take. Idempotent.
    for human in await db.audio_cache.find(
        {"manual_override": True, "word": {"$not": {"$regex": "#"}}}
    ).to_list(100_000):
        w = human["word"]
        entry = await db.dictionary_entries.find_one({"word": w}, {"_id": 0, "ipa": 1})
        phones = (ipa_to_arpabet((entry or {}).get("ipa") or "") or get_arpabet(w))
        if phones:
            arp = " ".join(phones)
            await db.pronunciation_prefs.update_one(
                {"word": w},
                {"$set": {"word": w, "arpabet": arp, "ipa": arpabet_to_ipa(phones),
                          "categories": classify_word(phones), "source": "dictionary",
                          "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True)
            PREFERRED_ARPA[w] = arp
        human.pop("_id", None)
        human.update({"word": f"{w}#human", "manual_override": False})
        await db.audio_cache.update_one({"word": f"{w}#human"}, {"$set": human}, upsert=True)
        await db.audio_cache.delete_many({"word": {"$in": [w, f"{w}#ph"]}})
        logger.info("dictionary: migrated human recording for %r to ElevenLabs phonemes", w)

    async def _revoice_archived_takes() -> None:
        """Coach takes that have no ElevenLabs re-voice yet get one (speech-to-
        speech), so members hear her pronunciation in the app voice."""
        await asyncio.sleep(30)
        for human in await db.audio_cache.find({"word": {"$regex": "#human$"}}).to_list(100_000):
            w = human["word"][:-6]
            if await db.audio_cache.find_one({"word": w, "manual_override": True}, {"_id": 1}):
                continue
            try:
                revoiced = await asyncio.to_thread(
                    revoice_recording, base64.b64decode(human["audio_b64"]))
            except Exception as e:
                logger.warning("revoice failed for %r: %s", w, e)
                continue
            await db.audio_cache.update_one(
                {"word": w},
                {"$set": {"word": w, "audio_b64": base64.b64encode(revoiced).decode("ascii"),
                          "manual_override": True, "source": "speech_to_speech",
                          "content_type": "audio/mpeg", "byte_size": len(revoiced),
                          "created_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True)
            logger.info("dictionary: re-voiced %r with ElevenLabs speech-to-speech", w)

    asyncio.create_task(_revoice_archived_takes())
    from watchdog import watchdog_loop
    asyncio.create_task(watchdog_loop(db))
    from supabase_auth import link_existing_users
    asyncio.create_task(link_existing_users(db))
    await db.users.create_index("supabase_sub", unique=True, sparse=True)
    # Scene ownership: pre-existing scenes have no uploader record; mark them
    # legacy (admin-only) without touching their content. Idempotent.
    await db.scenes.update_many(
        {"owner_email": {"$exists": False}},
        {"$set": {"owner_email": None, "legacy": True}},
    )
    await db.scenes.create_index("owner_email")
    await backfill_email_keys(db)
    # 90-day retention: TTL on a BSON datetime; backfill older scenes so the
    # rule applies uniformly (never expires legacy/admin scenes).
    await db.scenes.create_index("expires_at_dt", expireAfterSeconds=0)
    async for s in db.scenes.find(
        {"expires_at_dt": {"$exists": False}, "legacy": {"$ne": True}},
        {"_id": 1, "created_at": 1},
    ):
        try:
            created = datetime.fromisoformat(s["created_at"])
        except Exception:
            created = datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        await db.scenes.update_one(
            {"_id": s["_id"]},
            {"$set": {"expires_at_dt": created + timedelta(days=SCENE_RETENTION_DAYS)}},
        )
    # Clips the coach flagged as non-General-American speakers.
    for vid, reason in [("_Sjvjvbz5X0", "CBS News — 'Gavin' speaker not GA")]:
        await db.hidden_videos.update_one(
            {"video_id": vid},
            {"$setOnInsert": {"video_id": vid, "reason": reason, "channel_title": "CBS News",
                              "title": "", "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    # Ensure the caption_transcript_cache text index exists so the local
    # word-in-caption search works. Idempotent.
    try:
        await caption_service.ensure_local_indexes()
    except Exception as exc:
        logger.warning("caption local index bootstrap failed: %s", exc)

    async def _slur_backfill():
        try:
            import profanity
            await profanity.load(db)
            await caption_service.backfill_slur_flags()
        except Exception as exc:
            logger.warning("profanity backfill failed: %s", exc)
    asyncio.create_task(_slur_backfill())

    # Auto-kick channel ingest on cold start IF the transcript cache is
    # nearly empty, AND run a weekly refresh forever after so new uploads
    # keep flowing in. Runs in the background — doesn't block startup.
    # Idempotent: if another instance already started it, the job row will
    # be marked running and this will short-circuit.
    WEEKLY_INTERVAL_SECONDS = 7 * 24 * 3600     # 7 days
    DAILY_CHECK_SECONDS = 24 * 3600             # check every 24h

    async def _run_full_ingest() -> None:
        """One pass over all curated channels. Non-overlapping; a lock with no
        progress for 30 min is a crash leftover and is taken over."""
        rate_limited = False
        status = await db.ingest_status.find_one(
            {"job": "channels"}, {"_id": 0}
        )
        if status and status.get("running"):
            stale = True
            try:
                last = status.get("updated_at") or status.get("started_at") or ""
                stale = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() > 30 * 60
            except Exception:
                pass
            if not stale:
                return
            logger.warning("ingest supervisor: taking over stale lock from %s", status.get("started_at"))
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
            rate_limited = False
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
                if r.get("rate_limited"):
                    rate_limited = True
                    logger.warning("ingest: YouTube throttling — stopping pass after %d/%d channels; will retry tomorrow", i, len(ch_ids))
                    break
        finally:
            done_fields = {
                "running": False,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
            if not rate_limited:
                done_fields["last_full_finished_at"] = datetime.now(timezone.utc).isoformat()
            await db.ingest_status.update_one({"job": "channels"}, {"$set": done_fields})

    async def _ingest_supervisor():
        """Runs forever. On boot: if cache is thin, ingest right away.
        Then every 24h: if last full ingest was > 7 days ago, run again.
        """
        try:
            await asyncio.sleep(20)  # let pod finish booting
            # A fresh process means any "running" lock belongs to a dead run.
            await db.ingest_status.update_one(
                {"job": "channels", "running": True}, {"$set": {"running": False}}
            )
            indexed = await db.caption_transcript_cache.count_documents(
                {"has_transcript": True}
            )
            # Also re-run when the curated channel list changed since the
            # last full pass, so new channels show up without a manual click.
            import hashlib
            from caption_search import CURATED_HANDLES
            channel_sig = hashlib.sha1(
                ",".join(sorted(h["handle"].lower() for h in CURATED_HANDLES)).encode()
            ).hexdigest()[:12]
            status = await db.ingest_status.find_one({"job": "channels"}, {"_id": 0}) or {}
            last_full = status.get("last_full_finished_at")
            full_overdue = True
            if last_full:
                try:
                    full_overdue = (datetime.now(timezone.utc) - datetime.fromisoformat(
                        last_full.replace("Z", "+00:00"))).total_seconds() >= WEEKLY_INTERVAL_SECONDS
                except Exception:
                    full_overdue = True
            if indexed < 200 or status.get("channel_sig") != channel_sig or full_overdue:
                # A throttled pass never records a full finish, so without a
                # cooldown every redeploy re-ran the whole ingest (memory spike).
                recent_attempt = False
                last_try = status.get("finished_at") or status.get("started_at")
                if last_try and indexed >= 200 and status.get("channel_sig") == channel_sig:
                    try:
                        recent_attempt = (datetime.now(timezone.utc) - datetime.fromisoformat(
                            last_try.replace("Z", "+00:00"))).total_seconds() < DAILY_CHECK_SECONDS
                    except Exception:
                        recent_attempt = False
                if recent_attempt:
                    logger.info("ingest supervisor: skipping startup ingest (attempted %s)", last_try)
                else:
                    logger.info(
                        "ingest supervisor: startup ingest (indexed=%d, channels changed=%s)",
                        indexed, status.get("channel_sig") != channel_sig,
                    )
                    try:
                        await db.ingest_status.update_one(
                            {"job": "channels"}, {"$set": {"channel_sig": channel_sig}}, upsert=True
                        )
                        await _run_full_ingest()
                    except Exception as exc:
                        logger.warning("startup ingest failed: %s", exc)

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
