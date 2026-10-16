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
from phonetics import get_arpabet
import phoneme_ear as ear

logger = logging.getLogger("practice")

MAX_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 15
MIN_SECONDS = 0.25
ACCURATE_AT = 80
CLOSE_AT = 60

# Short, fixed coaching cues per General American phoneme (Azure en-US IPA set).
TIPS = {
    "ɪ": "Short, relaxed vowel as in 'sit' — tongue high but loose, lips neutral.",
    "i": "Long, tense vowel as in 'see' — spread the lips slightly.",
    "ɛ": "Open-mid vowel as in 'bed' — jaw a little lower than for 'bid'.",
    "æ": "Jaw open, tongue low and forward, as in 'cat' — more open than British 'a'.",
    "ʌ": "Central, relaxed vowel as in 'cup' — mouth slightly open, tongue neutral.",
    "ə": "Schwa — quick, unstressed, totally relaxed; don't give it a full vowel.",
    "ɑ": "Open back vowel as in 'father' — jaw drops, lips unrounded.",
    "ɔ": "As in 'thought' — many Americans merge this with /ɑ/; keep it open, barely rounded.",
    "ʊ": "Short vowel as in 'book' — lips loosely rounded, tongue high-back but relaxed.",
    "u": "As in 'food' — rounded lips, tongue high and back.",
    "eɪ": "Diphthong as in 'day' — start at /e/ and glide up toward /ɪ/.",
    "aɪ": "Diphthong as in 'my' — open start, glide up toward /ɪ/.",
    "oʊ": "Diphthong as in 'go' — round the lips and glide toward /ʊ/.",
    "aʊ": "Diphthong as in 'now' — open start, glide to rounded /ʊ/.",
    "ɔɪ": "Diphthong as in 'boy' — rounded start, glide toward /ɪ/.",
    "ɝ": "Stressed r-colored vowel as in 'bird' — curl or bunch the tongue, lips slightly rounded.",
    "ɚ": "Unstressed r-colored vowel as in 'butter' — keep the R quality, keep it short.",
    "ɑɹ": "As in 'car' — open /ɑ/ then pull the tongue back into a full American R.",
    "ɔɹ": "As in 'for' — rounded vowel gliding into a full American R.",
    "ɛɹ": "As in 'air' — open /ɛ/ gliding into an American R.",
    "ɪɹ": "As in 'here' — /ɪ/ gliding into an American R.",
    "ʊɹ": "As in 'tour' — rounded /ʊ/ gliding into an American R.",
    "ɹ": "American R — tongue tip pulled back and up (not touching), lips slightly rounded.",
    "r": "American R — tongue tip pulled back and up (not touching), lips slightly rounded.",
    "l": "Tongue tip touches behind the top teeth; at word ends the American L is dark (back of tongue raised).",
    "t": "Crisp /t/ with a puff of air at word starts; between vowels Americans often flap it (like a quick D).",
    "d": "Voiced /d/ — tongue tip behind the top teeth, vocal cords on.",
    "θ": "Voiceless TH as in 'think' — tongue tip lightly between the teeth, air flows.",
    "ð": "Voiced TH as in 'this' — tongue between the teeth with voice on; not /d/ or /z/.",
    "s": "Sharp /s/ — tongue groove, air over the tip.",
    "z": "Voiced /z/ — same as /s/ but with the voice on.",
    "ʃ": "SH as in 'she' — lips rounded, tongue a little back.",
    "ʒ": "As in 'measure' — voiced SH.",
    "tʃ": "CH as in 'church' — stop then release into SH.",
    "dʒ": "J as in 'judge' — stop then release into ZH, voiced.",
    "ŋ": "NG as in 'sing' — back of tongue up; don't add a hard G after it.",
    "n": "Tongue tip behind the top teeth, air through the nose.",
    "m": "Lips together, air through the nose.",
    "h": "Light breathy /h/ — don't drop it.",
    "w": "Round the lips tightly, then release into the vowel.",
    "j": "Y as in 'yes' — tongue high and forward, quick glide.",
    "v": "Top teeth on the bottom lip with voice on — not /w/ or /f/.",
    "f": "Top teeth on the bottom lip, air only.",
    "b": "Lips together, voiced release.",
    "p": "Lips together with a puff of air on release at word starts.",
    "k": "Back of tongue up with a puff of air at word starts.",
    "ɡ": "Back of tongue up, voiced.",
    "g": "Back of tongue up, voiced.",
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
            p.status, p.note = "needs_work", f"The R was held too long ({dur:.1f} s) — touch the R and move on."
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
    return bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"))


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
        return "Excellent", "Very close to a native American pronunciation."
    if score >= 85:
        return "Good", "Clearly American — one or two sounds could be sharper."
    if score >= 70:
        return "Okay — still needs practice", "Understandable, but at least one sound isn't American yet. Work on the sounds below."
    if score >= 50:
        return "Needs work", "The word is recognisable, but several sounds need work."
    return "Keep working", "Listen to the American version again and focus on the sounds below."


_ARPA_VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}


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
