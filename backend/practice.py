"""Practise This Word — member records a word, Azure Pronunciation Assessment scores it.

Audio is held in a temp dir for ffmpeg + the Azure call only; nothing is stored.
"""
import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from auth import _membership_status, consume_trial, is_admin_email, optional_login, rate_limit, require_access
from phonetics import ARPA_TO_IPA, CUSTOM_IPA, get_arpabet, ipa_to_arpabet
import phoneme_ear as ear
import difflib

logger = logging.getLogger("practice")

MAX_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 15
MIN_SECONDS = 0.25
ACCURATE_AT = 80
CLOSE_AT = 60

# Coaching cues per General American phoneme — wording from the All American Voice pronunciation guides.
TIPS = {
    'i': 'As in she. Tongue: the front part of the body of the tongue is arched high. Lips: smiling. Lower jaw: only slightly opened. Tongue tip rests at the lower gum ridge.',
    'ɪ': 'As in is. Tongue: the arch of the tongue lowers ever so slightly. Lips: smiling and slightly spread apart. Lower jaw: lowers slightly. Tongue tip rests at the lower gum ridge. A short vowel.',
    'ɛ': "As in best. Tongue: only slightly arched, with the tongue tip still resting at home base. Lips: smile in a wider position. Lower jaw: lowers a bit more. A short vowel — watch that you don't over-lengthen it.",
    'æ': 'As in at or class. Tongue: lying flat in the mouth with the focus on the front part; the tip remains at home base. Lips: wide open smile, teeth far apart. Lower jaw: open. Typically short, but its open shape asks for a little more length than ɪ.',
    'ʌ': 'As in lunch. Tongue: lies flat with the tip resting at home base. Lips: relaxed. Lower jaw: gently drop the jaw more to create a bigger space in the mouth. Similar to the schwa, but used in the stressed syllable with slightly more length.',
    'ə': 'As in the. Tongue: relaxed, with a gentle, natural arch; the tip rests at home base. Lips: relaxed — neither rounded nor smiling. Jaw and lips free of tension. A short vowel heard in unstressed syllables. Keep the tongue tip at the lower gum ridge to avoid an intrusive r.',
    'ɑ': 'As in father — the most open sound in the American accent. Tongue: the back is flat with the tip resting at home base. Lips: stretched and opened forward. Lower jaw: its most open position, teeth far apart. A long vowel.',
    'ɔ': 'As in call. Tongue: the back is only slightly arched; the tip rests at home base. Lips: rounded and protruded — you should feel sensation in the cheeks, and your thumb should fit between your lips. Lower jaw: open, released forward and down. A long vowel.',
    'ʊ': 'As in should. Tongue: the arch at the back lowers slightly; the tip rests at home base. Lips: open up a bit more and actively round into the shape of a circle. Lower jaw: opens slightly more. A short vowel.',
    'u': "As in who or tune. Tongue: the arch of the back of the tongue is highest — don't let it pull back into the throat; the tip rests at home base. Lips: stretched forward in a small round circle. Lower jaw: only slightly open. A long vowel. After n, t, d, s or l Americans drop the 'liquid u' (ju) and use the pure u: tune, not tyune.",
    'eɪ': 'As in sail. Two front vowels: e (similar to ɛ in best, but the jaw does not open as much) gliding to the weaker ɪ. This sound can be lengthened, but the length comes from the first sound rather than the second.',
    'aɪ': 'As in my. An open first sound and a closed, weaker second sound. Look in the mirror and make sure you open up wide enough for the first sound; let the tongue lie flat before it arches up for the second. The length comes from the first sound.',
    'oʊ': 'As in boat. Two back vowels: the pure o gliding to ʊ as in should. Feel the jaw move from open to slightly closed; the tongue is arched in the back and the lips are rounded. The length comes from the first sound.',
    'aʊ': 'As in now. Starts very open on ɑ as in father — the most open vowel in the accent — then the arch in the back of the tongue raises for ʊ. Lips start open and close to a more rounded position. The length comes from the first sound.',
    'ɔɪ': 'As in toy. Starts on the back vowel ɔ as in call and glides to ɪ. Look in the mirror: the tongue arch moves from back to front, the jaw from a wide to a small opening, and the lips from rounded to smiling. The length comes from the first sound.',
    'ɝ': 'As in serve. Tongue: remove the tip from home base — the tip curls as the r is activated and you should feel tension in the tip. The body of the tongue should not pull back; the middle of the tongue is arched high. Lips: relaxed. Lower jaw: only slightly opened. Used in the stressed syllable (journey, herbal).',
    'ɚ': 'As in mother. The tongue tip curls but is more relaxed, not as tense as ɝ in serve. Lips relaxed, jaw slightly opened. Short in duration — if this sound is stressed or lengthened the accent will begin to sound unnatural.',
    'ɑɹ': "As in car. The back vowel ɑ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from home base. Don't let the back of the tongue pull back.",
    'ɔɹ': "As in horse. The back vowel ɔ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from home base. Don't let the back of the tongue pull back.",
    'ɛɹ': "As in Claire. The front vowel ɛ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from home base. Don't let the back of the tongue pull back.",
    'ɪɹ': "As in fears. The front vowel ɪ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from home base. Don't let the back of the tongue pull back.",
    'ʊɹ': "As in poor. The back vowel ʊ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from home base. Don't let the back of the tongue pull back.",
    'ɹ': 'As in red. Either the tongue tip raises just behind the upper gum ridge, curled and pointed up to the hard palate without touching it, with the lips rounding — or the back of the tongue raises and retracts, pressing against the upper back teeth, with the tip less active. Use whichever method is best for you.',
    'r': 'As in red. Either the tongue tip raises just behind the upper gum ridge, curled and pointed up to the hard palate without touching it, with the lips rounding — or the back of the tongue raises and retracts, pressing against the upper back teeth, with the tip less active. Use whichever method is best for you.',
    'l': 'As in love. The tip and blade of the tongue make contact with the upper gum ridge and the air passes out at the sides of the tongue. The American l is darker than other accents — imagine the tip and blade pushing forward against the gum ridge as if pushing against a wall. The tip is tense; the rest of the tongue broad, flat and free of tension.',
    't': 'As in toast — the tip of the tongue touches the upper gum ridge. Fully sounded at the start of a word, at the start of a stressed syllable, and at the end of a word (draft, apt, vast). Lightly voiced, sounding like d, after a stressed syllable (matter, water) and between a vowel, r and vowel (quarter, parting). Held, with no release, before another consonant (football, twenty).',
    'd': 'As in doe. Firmly and quickly apply pressure with the tongue tip on the upper gum ridge, then let the tip drop back down to home base. Voiced.',
    'θ': "As in thin. The tip of the tongue rests between the upper and lower teeth and the air passes through the mouth. Keep the rest of the mouth relaxed and watch that th doesn't sound like d — that happens if the tip pulls back. The tip needs to be between the teeth.",
    'ð': "As in then. The tip of the tongue rests between the upper and lower teeth and you add voice. Keep the rest of the mouth relaxed and watch that th doesn't sound like d — that happens if the tip pulls back. The tip needs to be between the teeth.",
    's': "As in sue. The tip of the tongue is positioned toward the upper gum ridge but doesn't actually touch. Lower jaw relaxed, teeth almost closed. Voiceless.",
    'z': "As in zoo. The tip of the tongue is positioned toward the upper gum ridge but doesn't actually touch. Lower jaw relaxed, teeth almost closed. Voiced.",
    'ʃ': 'As in shoe. The tip is positioned toward the upper gum ridge without touching; feel the sides of the tongue touch the upper teeth as the body of the tongue raises high. Lower jaw relaxed, teeth almost closed. Voiceless.',
    'ʒ': 'As in genre. The tip is positioned toward the upper gum ridge without touching; feel the sides of the tongue touch the upper teeth as the body of the tongue raises high. Lower jaw relaxed, teeth almost closed. Voiced.',
    'tʃ': 'As in chin. The tip makes contact with the upper gum ridge (as for t), then quickly moves to the sh position just behind it without touching — fast enough to sound like one sound. Lower jaw relaxed. Voiceless.',
    'dʒ': 'As in gin. The tip makes contact with the upper gum ridge (as for d), then quickly moves to the zh position just behind it without touching — fast enough to sound like one sound. Lower jaw relaxed. Voiced.',
    'ŋ': 'As in sing. The back of the tongue raises to make contact with the soft palate; as the sound is voiced, let it drop slightly away. The tip stays at home base. Words ending in -ing should be pronounced — avoid the temptation to drop the final g sound.',
    'n': "As in no. The tip of the tongue touches the upper gum ridge, the body of the tongue is high, and the sound resonates in the nasal cavity. The tip drops to form the next sound — watch that the tongue doesn't pull back.",
    'm': 'As in may. The upper lip makes contact with the lower lip — closed but not overly tense. Lower jaw relaxed, tongue tip at the lower gum ridge. You may feel a buzzing on the lips.',
    'h': 'As in home. The air travels through the pharynx — imagine letting out a heavy breath onto a mirror or a window on a cold day. Unvoiced.',
    'w': 'As in way. The upper and lower lips round. Lower jaw relaxed, tongue tip at the lower gum ridge, and the back of the tongue can arch high.',
    'j': 'As in you. The tip rests at the lower gum ridge and the front part of the body of the tongue raises high towards the hard palate — you will feel it touching the sides of the upper teeth. Then let the tongue drop down as you voice the sound.',
    'v': 'As in vine. The lower lip makes contact with the upper teeth and the breath travels between the teeth and lower lip. Lower jaw relaxed, tongue tip at the lower gum ridge. Voiced.',
    'f': 'As in fine. The lower lip makes contact with the upper teeth and the breath travels between the teeth and lower lip. Lower jaw relaxed, tongue tip at the lower gum ridge. Voiceless.',
    'b': 'As in bay. The upper lip makes contact with the lower lip — closed but not overly tense — then the lips open as they release quickly. Lower jaw relaxed, tongue tip at the lower gum ridge. Voiced.',
    'p': 'As in pay. The upper lip makes contact with the lower lip — closed but not overly tense — then the lips open as they release quickly. Lower jaw relaxed, tongue tip at the lower gum ridge. Voiceless.',
    'k': 'As in curl. The back of the tongue makes contact with the soft palate, then quickly drops and the breath travels through the open space. Lower jaw relaxed, tongue tip at the lower gum ridge. Voiceless.',
    'ɡ': 'As in girl. The back of the tongue makes contact with the soft palate, then quickly drops and the breath travels through the open space. Lower jaw relaxed, tongue tip at the lower gum ridge. Voiced.',
    'g': 'As in girl. The back of the tongue makes contact with the soft palate, then quickly drops and the breath travels through the open space. Lower jaw relaxed, tongue tip at the lower gum ridge. Voiced.',
}


class PhonemeScore(BaseModel):
    expected: str
    score: Optional[float] = None
    heard: Optional[str] = None
    status: str  # accurate | close | needs_work | unknown
    start_s: Optional[float] = None
    end_s: Optional[float] = None
    ear: Optional[str] = None  # confirmed | missing | unsure
    note: Optional[str] = None
    flap: bool = False  # American flapped T expected in this slot
    azure_expected: Optional[str] = None  # set when Azure picked a non-American variant


class NeedsWork(BaseModel):
    phoneme: str
    score: Optional[float] = None
    heard: Optional[str] = None
    tip: Optional[str] = None
    confirmed: bool = False  # the ear heard a different sound in this slot
    overdone: bool = False   # sound present but held/leaned on too long
    note: Optional[str] = None


class StressCheck(BaseModel):
    verdict: str  # ok | wrong | unsure
    expected_index: int
    heard_index: Optional[int] = None
    pattern_expected: str
    pattern_heard: Optional[str] = None
    note: Optional[str] = None


class AssessResponse(BaseModel):
    word: str
    assessable: bool
    reason: Optional[str] = None
    recognized: Optional[str] = None
    score: Optional[float] = None       # 0–100 (after confirmed-miss adjustment)
    score10: Optional[float] = None     # same, out of 10
    azure_score: Optional[float] = None
    accuracy: Optional[float] = None
    band: Optional[str] = None
    summary: Optional[str] = None
    phonemes: List[PhonemeScore] = []
    accurate: List[str] = []
    needs_work: List[NeedsWork] = []
    trial_locked: bool = False  # trial user has now used their one analysis for this word
    ear: Optional[dict] = None  # admin-only readout: {heard, checks, status}
    stress: Optional[StressCheck] = None
    syllables: List[dict] = []  # [{text, start_s, end_s}] from Azure, single-word lookups only
    expected_vowels: int = 0
    extra_syllables: int = 0


EXTRA_SYLLABLE_PENALTY = 15


def check_extra_syllables(out: "AssessResponse", heard: Optional[dict]) -> None:
    """More vowel nuclei heard than the American word has → an added syllable (alu-MIN-i-um)."""
    if not heard or not out.expected_vowels:
        return
    extra = int(heard.get("heard_vowels") or 0) - out.expected_vowels
    if extra < 1:
        return
    out.extra_syllables = extra
    pattern = None
    if out.syllables:
        phones = our_phones(out.word.lower())
        stresses = [ph[-1] for ph in phones if ph[-1].isdigit()]
        idx = stresses.index("1") if "1" in stresses else -1
        pattern = _display_pattern([s["text"] for s in out.syllables], idx)
    note = f"We heard {out.expected_vowels + extra} syllables — the American word has {out.expected_vowels}"
    note += f": {pattern}." if pattern else "."
    out.needs_work.insert(0, NeedsWork(phoneme="extra syllable", note=note, confirmed=True,
                                       tip="Say it the American way, with no added vowel. Listen to the reference and match the syllable count."))
    out.score = max(0.0, min(float(out.score or 0) - EXTRA_SYLLABLE_PENALTY * extra, MISS_CAP))
    out.band, out.summary = _band(out.score)
    out.score10 = round(out.score / 10, 1)


STRESS_PENALTY = 10
R_SOUNDS = {"ɑɹ", "ɔɹ", "ɛɹ", "ɪɹ", "ʊɹ", "ɝ", "ɚ", "ɹ", "r"}
R_MAX_S = 0.45          # word-internal R-coloured sound held this long is being leaned on
R_MAX_FINAL_S = 0.70    # finals are naturally longer (Hannah: 0.37–0.61 s)
OVERDONE_PENALTY = 10


def check_held_r(out: "AssessResponse") -> None:
    """Flag R-coloured sounds the speaker holds too long (Azure phoneme timings)."""
    timed = [p for p in out.phonemes if p.start_s is not None and p.end_s is not None]
    if not timed:
        return
    hits = []
    for i, p in enumerate(timed):
        if p.expected not in R_SOUNDS or p.ear == "missing":
            continue
        dur = p.end_s - p.start_s
        limit = R_MAX_FINAL_S if i == len(timed) - 1 else R_MAX_S
        if dur >= limit:
            p.status, p.note = "needs_work", "The r was held too long. Pronounce the r but don’t linger on the sound."
            hits.append(p)
    if not hits:
        return
    seen = {n.phoneme for n in out.needs_work}
    for p in hits:
        if p.expected in seen:
            continue
        seen.add(p.expected)
        out.needs_work.append(NeedsWork(phoneme=p.expected, score=p.score, tip=TIPS.get(p.expected), overdone=True, note=p.note))
    out.accurate = [a for a in out.accurate if a not in {p.expected for p in hits}]
    out.score = max(0.0, min(float(out.score or 0) - OVERDONE_PENALTY * len({p.expected for p in hits}), MISS_CAP))
    out.band, out.summary = _band(out.score)
    out.score10 = round(out.score / 10, 1)


def _display_pattern(graphemes: List[str], idx: int) -> str:
    return "-".join(g.upper() if i == idx else g.lower() for i, g in enumerate(graphemes))


def stress_check(word: str, syllables: List[dict], wav_bytes: bytes) -> Optional[StressCheck]:
    """Compare the loudest/longest syllable with the CMU primary stress. Conservative:
    only 'wrong' when another syllable is clearly louder AND not shorter."""
    phones = get_arpabet(word) or []
    stresses = [ph[-1] for ph in phones if ph[-1].isdigit()]
    if len(stresses) < 2 or len(stresses) != len(syllables) or "1" not in stresses:
        return None
    expected = stresses.index("1")
    import io
    import numpy as np
    import soundfile as sf
    audio, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    rms, dur = [], []
    for s in syllables:
        a, b = int(s["start_s"] * sr), int(s["end_s"] * sr)
        seg = audio[a:b]
        rms.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
        dur.append(max(0.0, s["end_s"] - s["start_s"]))
    graphemes = [s["text"] for s in syllables]
    heard = int(np.argmax(rms))
    pattern_expected = _display_pattern(graphemes, expected)
    if heard == expected or rms[expected] >= 0.85 * rms[heard]:
        return StressCheck(verdict="ok", expected_index=expected, heard_index=expected, pattern_expected=pattern_expected,
                           pattern_heard=pattern_expected)
    if rms[heard] >= 1.35 * max(rms[expected], 1e-6) and dur[heard] >= 0.8 * dur[expected]:
        return StressCheck(
            verdict="wrong", expected_index=expected, heard_index=heard, pattern_expected=pattern_expected,
            pattern_heard=_display_pattern(graphemes, heard),
            note=f"The stress landed on “{graphemes[heard]}” — Americans say {pattern_expected}.",
        )
    return StressCheck(verdict="unsure", expected_index=expected, heard_index=heard, pattern_expected=pattern_expected)


MISS_PENALTY = 20   # points off the 100-scale per sound the ear confirms as missing/replaced
MISS_CAP = 75       # a confirmed miss can never read "Excellent"


def apply_ear(out: "AssessResponse", heard: Optional[dict]) -> None:
    """Fold the recogniser's per-window verdicts into the Azure-based result."""
    if not heard:
        return
    checks = heard.get("checks") or []
    for p, c in zip(out.phonemes, checks):
        p.ear = c.get("verdict")
        if c["verdict"] == "missing":
            p.status = "needs_work"
            p.heard = c.get("heard") or p.heard
            p.note = c.get("note")
            if p.score is None or p.score > CLOSE_AT - 1:
                p.score = float(CLOSE_AT - 1)
    misses = [p for p in out.phonemes if p.ear == "missing"]
    if misses:
        distinct = {p.expected for p in misses}
        out.score = max(0.0, min(float(out.score or 0) - MISS_PENALTY * len(distinct), MISS_CAP))
        out.band, out.summary = _band(out.score)
        out.accurate = sorted({p.expected for p in out.phonemes if p.status == "accurate" and p.ear != "missing"})
        seen = {n.phoneme for n in out.needs_work}
        for p in misses:
            if p.expected in seen:
                for n in out.needs_work:
                    if n.phoneme == p.expected:
                        n.confirmed, n.heard, n.score, n.note = True, p.heard or n.heard, min(n.score or 100, p.score or 0), p.note
                continue
            seen.add(p.expected)
            out.needs_work.append(NeedsWork(phoneme=p.expected, score=p.score, heard=p.heard, tip=TIPS.get(p.expected), confirmed=True, note=p.note))
        out.needs_work.sort(key=lambda n: (not n.confirmed, n.score or 0))
    out.score10 = round((out.score or 0) / 10, 1)


def enabled() -> bool:
    """Preview-only until explicitly forced: needs the Azure key AND the ear worker env
    (/opt/ear-venv exists only in preview and is never shipped). PRACTICE_MODE=force
    is the deliberate production opt-in once the ear is hosted externally."""
    mode = os.environ.get("PRACTICE_MODE", "").lower()
    has_key = bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"))
    if not has_key:
        return False
    if mode == "force":
        return True
    return mode == "on" and os.path.exists(ear.EAR_PYTHON)


def _to_wav(src: Path, dst: Path) -> float:
    """Convert any browser recording to 16 kHz mono PCM; returns duration in seconds."""
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", "-t", str(MAX_SECONDS), "-y", str(dst)],
        capture_output=True, text=True, timeout=20,
    )
    if p.returncode or not dst.exists():
        raise HTTPException(status_code=415, detail="We couldn't read that recording. Please try again.")
    return max(0.0, (dst.stat().st_size - 44) / 32000.0)


def _assessment_header(reference: str) -> str:
    cfg = {
        "ReferenceText": reference,
        "GradingSystem": "HundredMark",
        "Granularity": "Phoneme",
        "Dimension": "Comprehensive",
        "EnableMiscue": True,
        "PhonemeAlphabet": "IPA",
        "NBestPhonemeCount": 3,
    }
    return base64.b64encode(json.dumps(cfg, separators=(",", ":")).encode()).decode()


async def _call_azure(wav: bytes, reference: str) -> dict:
    region = os.environ["AZURE_SPEECH_REGION"]
    url = f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    headers = {
        "Accept": "application/json",
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        "Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
        "Pronunciation-Assessment": _assessment_header(reference),
    }
    params = {"language": "en-US", "format": "detailed"}
    r = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(url, params=params, headers=headers, content=wav)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="The pronunciation checker took too long. Please try again.")
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="The pronunciation checker is unreachable right now. Please try again shortly.")
        if r.status_code == 200 or attempt == 1:
            break
        logger.warning("Azure speech %s on attempt 1: %s — retrying", r.status_code, r.text[:200])
        await asyncio.sleep(1.5)
    if r.status_code in (401, 403):
        logger.error("Azure speech auth failed (%s)", r.status_code)
        raise HTTPException(status_code=503, detail="The pronunciation checker isn't configured correctly. Please contact support.")
    if r.status_code == 429:
        raise HTTPException(status_code=503, detail="The pronunciation checker is busy. Please try again in a moment.")
    if r.status_code != 200:
        logger.error("Azure speech error %s: %s", r.status_code, r.text[:300])
        raise HTTPException(status_code=502, detail="The pronunciation checker returned an error. Please try again.")
    try:
        return r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="The pronunciation checker returned an unreadable result.")


def _band(score: float) -> tuple[str, str]:
    if score >= 95:
        return "Excellent", "Very close to authentic American pronunciation."
    if score >= 85:
        return "Good", "Great job but one or two sounds could be sharper."
    if score >= 70:
        return "Okay — still needs practice", "Understandable, but at least one sound is off. Work on the sounds below."
    if score >= 50:
        return "Needs work", "The word is recognisable, but several sounds need work."
    return "Keep working", "Listen to the word again and focus on the sounds below."


_ARPA_VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
_R_COMBO = {"ɑ": "ɑɹ", "ɔ": "ɔɹ", "ɛ": "ɛɹ", "ɪ": "ɪɹ", "ʊ": "ʊɹ", "ə": "ɚ", "ʌ": "ɝ"}


def our_phones(word: str) -> List[str]:
    """The app's own American pronunciation (coach IPA wins over CMU) as ARPABET phones."""
    if word in CUSTOM_IPA:
        return ipa_to_arpabet(CUSTOM_IPA[word]) or []
    return get_arpabet(word) or []


def expected_sequence(phones: List[str]) -> List[str]:
    """ARPABET → Azure-style IPA symbols (vowel+R merged into r-coloured combos)."""
    seq: List[str] = []
    for ph in phones:
        base, stress = ph.rstrip("012"), ph[-1] if ph[-1].isdigit() else ""
        sym = ARPA_TO_IPA.get(base, "")
        if base == "AH" and stress == "0":
            sym = "ə"
        if base == "ER" and stress == "0":
            sym = "ɚ"
        if sym == "ɹ" and seq and seq[-1] in _R_COMBO:
            seq[-1] = _R_COMBO[seq[-1]]
            continue
        seq.append(sym)
    return seq


def align_expected(ours: List[str], azure: List[str]) -> List[Optional[str]]:
    """Per Azure slot: our symbol when Azure chose a different variant, else None."""
    out: List[Optional[str]] = [None] * len(azure)
    sm = difflib.SequenceMatcher(a=azure, b=ours, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                out[i1 + k] = ours[j1 + k]
    return out


def flap_flags(word: str, azure_phonemes: List[str]) -> List[bool]:
    """Which Azure 't' slots are American flaps (T between a vowel/R and an unstressed vowel or syllabic L).

    Uses CMU stress marks; falls back to all-False when the T counts don't line up.
    """
    phones = get_arpabet(word) or []
    flags_cmu: List[bool] = []
    for i, ph in enumerate(phones):
        if ph != "T":
            continue
        prev = phones[i - 1] if i > 0 else ""
        nxt = phones[i + 1] if i + 1 < len(phones) else ""
        prev_ok = prev[:2] in _ARPA_VOWELS or prev == "R"
        nxt_ok = (nxt[:2] in _ARPA_VOWELS and nxt.endswith("0")) or nxt == "L"
        flags_cmu.append(prev_ok and nxt_ok)
    t_slots = [i for i, p in enumerate(azure_phonemes) if p == "t"]
    out = [False] * len(azure_phonemes)
    if len(t_slots) != len(flags_cmu):
        return out
    for slot, f in zip(t_slots, flags_cmu):
        out[slot] = f
    return out


def _pa(item: dict) -> dict:
    """Azure REST puts scores flat on the item; the SDK nests them under PronunciationAssessment."""
    return {**item, **(item.get("PronunciationAssessment") or {})}


def _interpret(word: str, result: dict) -> AssessResponse:
    status = result.get("RecognitionStatus")
    if status in ("InitialSilenceTimeout", "NoMatch", "BabbleTimeout"):
        return AssessResponse(word=word, assessable=False,
                              reason="We couldn't hear the word clearly. Try again a little closer to the microphone.")
    if status != "Success":
        return AssessResponse(word=word, assessable=False,
                              reason="The recording couldn't be assessed. Please record the word again.")
    nbest = _pa((result.get("NBest") or [{}])[0])
    words = [_pa(w) for w in nbest.get("Words", [])]
    words = [w for w in words if w.get("ErrorType") != "Insertion"]
    if not words or all(w.get("ErrorType") == "Omission" for w in words):
        return AssessResponse(word=word, assessable=False, recognized=nbest.get("Display"),
                              reason="We didn't hear the word itself. Say just the word, then press Stop.")

    phonemes: List[PhonemeScore] = []
    syllables: List[dict] = []
    expected_vowels = 0
    for w in words:
        word_text = w.get("Word") or ""
        if len(words) == 1:
            syllables = [{"text": s.get("Grapheme") or s.get("Syllable") or "", "start_s": (s.get("Offset") or 0) / 1e7,
                          "end_s": ((s.get("Offset") or 0) + (s.get("Duration") or 0)) / 1e7} for s in w.get("Syllables", [])]
        w_phonemes: List[PhonemeScore] = []
        for p in w.get("Phonemes", []):
            p = _pa(p)
            exp = p.get("Phoneme") or ""
            sc = p.get("AccuracyScore")
            heard = None
            alts = p.get("NBestPhonemes") or []
            if alts and alts[0].get("Phoneme") and alts[0]["Phoneme"] != exp and (alts[0].get("Score") or 0) > (sc or 0):
                heard = alts[0]["Phoneme"]
            if sc is None:
                st = "unknown"
            elif sc >= ACCURATE_AT:
                st = "accurate"
            elif sc >= CLOSE_AT:
                st = "close"
            else:
                st = "needs_work"
            w_phonemes.append(PhonemeScore(
                expected=exp, score=sc, heard=heard, status=st,
                start_s=(p.get("Offset") or 0) / 1e7 if p.get("Offset") is not None else None,
                end_s=((p.get("Offset") or 0) + (p.get("Duration") or 0)) / 1e7 if p.get("Offset") is not None else None,
            ))
        for ps, is_flap in zip(w_phonemes, flap_flags(word_text, [ps.expected for ps in w_phonemes])):
            ps.flap = is_flap
        # Azure accepts any dictionary variant (PROH-cess); we insist on the app's American one.
        phones = our_phones(word_text.lower())
        expected_vowels += sum(1 for ph in phones if ph.rstrip("012") in _ARPA_VOWELS)
        for ps, ours in zip(w_phonemes, align_expected(expected_sequence(phones), [p.expected for p in w_phonemes])):
            if ours and ours in ear.EXPECTED:
                ps.azure_expected, ps.expected = ps.expected, ours
        phonemes.extend(w_phonemes)

    score = nbest.get("PronScore")
    accuracy = nbest.get("AccuracyScore")
    if score is None:
        return AssessResponse(word=word, assessable=False, recognized=nbest.get("Display"),
                              reason="The recording couldn't be scored. Please record the word again.")
    band, summary = _band(float(score))
    accurate = sorted({p.expected for p in phonemes if p.status == "accurate"})
    seen = set()
    needs: List[NeedsWork] = []
    for p in phonemes:
        if p.status in ("needs_work", "close") and p.expected not in seen:
            seen.add(p.expected)
            needs.append(NeedsWork(phoneme=p.expected, score=p.score, heard=p.heard, tip=TIPS.get(p.expected)))
    needs.sort(key=lambda n: n.score or 0)
    return AssessResponse(
        word=word, assessable=True, recognized=nbest.get("Display"),
        score=round(float(score)), score10=round(float(score) / 10, 1), azure_score=round(float(score)),
        accuracy=round(float(accuracy)) if accuracy is not None else None,
        band=band, summary=summary, phonemes=phonemes, accurate=accurate, needs_work=needs, syllables=syllables,
        expected_vowels=expected_vowels,
    )


def create_practice_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(prefix="/practice", tags=["practice"])

    async def _trial_used(email: str, norm: str) -> bool:
        user = await db.users.find_one({"email": email}, {"_id": 0, "practice_words": 1})
        return norm in (user or {}).get("practice_words", [])

    @router.get("/status")
    async def status(request: Request, word: Optional[str] = None):
        """enabled + whether a trial user has already spent their one analysis on `word`."""
        locked = False
        norm = re.sub(r"\s+", " ", (word or "").strip()).lower()
        if enabled() and norm:
            email = await optional_login(request, db)
            if email:
                ms = await _membership_status(db, email)
                if ms["status"] != "active":
                    locked = await _trial_used(email, norm)
        return {"enabled": enabled(), "locked": locked}

    @router.post("/assess", response_model=AssessResponse)
    async def assess(request: Request, word: str = Form(...), audio: UploadFile = File(...)):
        if not enabled():
            raise HTTPException(status_code=503, detail="Pronunciation practice isn't available right now.")
        reference = re.sub(r"\s+", " ", (word or "").strip())
        if not reference or len(reference) > 80 or not re.fullmatch(r"[A-Za-z' \-]+", reference):
            raise HTTPException(status_code=400, detail="Please search for a word first.")
        norm = reference.lower()
        actor = await require_access(request, db, kind="word", word=norm)
        # Free trial: one analysis per trial word.
        if not actor.is_subscriber and await _trial_used(actor.email, norm):
            raise HTTPException(status_code=402, detail={"code": "practice_exhausted", "kind": "practice"})
        rate_limit(f"practice:{actor.email}", 40, 3600)

        data = await audio.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="That recording is too long. Say just the word and press Stop.")
        if len(data) < 200:
            raise HTTPException(status_code=400, detail="The recording was empty. Press Record, say the word, then Stop.")

        with tempfile.TemporaryDirectory(prefix="pt-practice-") as d:
            src = Path(d) / "take.bin"
            wav = Path(d) / "take.wav"
            src.write_bytes(data)
            seconds = await asyncio.to_thread(_to_wav, src, wav)
            if seconds < MIN_SECONDS:
                raise HTTPException(status_code=400, detail="The recording was too short. Press Record, say the word, then Stop.")
            wav_bytes = wav.read_bytes()
        del data
        result = await _call_azure(wav_bytes, reference)
        out = _interpret(reference, result)
        heard = None
        if out.assessable and ear.available():
            windows = [{"expected": p.expected, "start_s": p.start_s or 0.0, "end_s": p.end_s or 0.0, "flap": p.flap} for p in out.phonemes]
            try:
                heard = await asyncio.to_thread(ear.listen, wav_bytes, windows)
            except Exception as exc:  # noqa: BLE001
                logger.warning("phoneme ear failed: %s", exc)
            apply_ear(out, heard)
            check_extra_syllables(out, heard)
        if out.assessable:
            check_held_r(out)
        if out.assessable and out.syllables:
            try:
                out.stress = await asyncio.to_thread(stress_check, reference, out.syllables, wav_bytes)
            except Exception as exc:  # noqa: BLE001
                logger.warning("stress check failed: %s", exc)
            if out.stress and out.stress.verdict == "wrong":
                out.score = max(0.0, min(float(out.score or 0) - STRESS_PENALTY, MISS_CAP))
                out.band, out.summary = _band(out.score)
                out.score10 = round(out.score / 10, 1)
        del wav_bytes
        if is_admin_email(actor.email):
            out.ear = {**ear.status(), "heard": (heard or {}).get("heard"), "checks": (heard or {}).get("checks")}
        await consume_trial(db, actor)
        if not actor.is_subscriber and out.assessable:
            await db.users.update_one({"email": actor.email}, {"$addToSet": {"practice_words": norm}})
            out.trial_locked = True
        return out

    return router
