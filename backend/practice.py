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

from auth import consume_trial, rate_limit, require_access

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


class NeedsWork(BaseModel):
    phoneme: str
    score: Optional[float] = None
    heard: Optional[str] = None
    tip: Optional[str] = None


class AssessResponse(BaseModel):
    word: str
    assessable: bool
    reason: Optional[str] = None
    recognized: Optional[str] = None
    score: Optional[float] = None
    accuracy: Optional[float] = None
    band: Optional[str] = None
    summary: Optional[str] = None
    phonemes: List[PhonemeScore] = []
    accurate: List[str] = []
    needs_work: List[NeedsWork] = []


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
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, params=params, headers=headers, content=wav)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="The pronunciation checker took too long. Please try again.")
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="The pronunciation checker is unreachable right now. Please try again shortly.")
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
    if score >= 85:
        return "Excellent", "Very close to a native American pronunciation."
    if score >= 70:
        return "Good", "Clearly understandable — a couple of sounds could be sharper."
    if score >= 50:
        return "Getting there", "The word is recognisable, but several sounds need work."
    return "Keep working", "Listen to the American version again and focus on the sounds below."


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
    for w in words:
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
            phonemes.append(PhonemeScore(expected=exp, score=sc, heard=heard, status=st))

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
        score=round(float(score)), accuracy=round(float(accuracy)) if accuracy is not None else None,
        band=band, summary=summary, phonemes=phonemes, accurate=accurate, needs_work=needs,
    )


def create_practice_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter(prefix="/practice", tags=["practice"])

    @router.get("/status")
    async def status():
        return {"enabled": enabled()}

    @router.post("/assess", response_model=AssessResponse)
    async def assess(request: Request, word: str = Form(...), audio: UploadFile = File(...)):
        if not enabled():
            raise HTTPException(status_code=503, detail="Pronunciation practice isn't available right now.")
        reference = re.sub(r"\s+", " ", (word or "").strip())
        if not reference or len(reference) > 80 or not re.fullmatch(r"[A-Za-z' \-]+", reference):
            raise HTTPException(status_code=400, detail="Please search for a word first.")
        norm = reference.lower()
        actor = await require_access(request, db, kind="word", word=norm)
        rate_limit(f"practice:{actor.email}", 20, 3600)

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
        del wav_bytes
        out = _interpret(reference, result)
        await consume_trial(db, actor)
        return out

    return router
