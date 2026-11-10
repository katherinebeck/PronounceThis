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
import formants
import fricatives
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
    'ɪ': 'The arch of the tongue lowers ever so slightly. Lips: smiling and slightly spread apart. Lower jaw: lowers slightly. Tongue tip rests at the lower gum ridge. This vowel is short in length.',
    'ɛ': "Tongue: only slightly arched, with the tongue tip still resting at the lower gum ridge. Lips: smile in a wider position. Lower jaw: lowers a bit more. A short vowel — watch that you don't over-lengthen it.",
    'æ': 'Tongue: lies flat in the mouth with the tongue tip at the lower gum ridge. Lips: wide open smile, teeth far apart. Lower jaw: open.',
    'ʌ': 'Tongue: lies flat with the tip resting at the lower gum ridge. Lips: relaxed. Lower jaw: gently drop the jaw more to create a bigger space in the mouth. Similar to the schwa, but used in the stressed syllable with slightly more length.',
    'ə': 'Tongue: relaxed, with a gentle, natural arch; the tip rests at the lower gum ridge. Lips: relaxed — neither rounded nor smiling. Jaw and lips free of tension. A short vowel heard in unstressed syllables. Keep the tongue tip at the lower gum ridge to avoid an intrusive r.',
    'ɑ': 'As in father — the most open sound in the American accent. Tongue: the back is flat with the tip resting at the lower gum ridge. Lips: stretched and opened forward. Lower jaw: its most open position, teeth far apart. A long vowel.',
    'ɔ': 'As in call. Tongue: the back is only slightly arched; the tip rests at the lower gum ridge. Lips: rounded and protruded — you should feel sensation in the cheeks, and your thumb should fit between your lips. Lower jaw: open, released forward and down. A long vowel.',
    'ʊ': 'The arch at the back of the tongue lowers slightly; the tip rests at the lower gum ridge. Lips: open up and actively round into the shape of a circle. Lower jaw: opens slightly. This is a short vowel sound.',
    'u': "As in who or tune. Tongue: the arch of the back of the tongue is highest — don't let it pull back into the throat; the tip rests at the lower gum ridge. Lips: stretched forward in a small round circle. Lower jaw: only slightly open. A long vowel. After n, t, d, s or l Americans drop the 'liquid u' (ju) and use the pure u: tune, not tyune.",
    'eɪ': 'As in sail. Two front vowels: e (similar to ɛ in best, but the jaw does not open as much) gliding to the weaker ɪ. This sound can be lengthened, but the length comes from the first sound rather than the second.',
    'aɪ': 'As in my. An open first sound and a closed, weaker second sound. Look in the mirror and make sure you open up wide enough for the first sound; let the tongue lie flat before it arches up for the second. The length comes from the first sound.',
    'oʊ': 'As in boat. Two back vowels: the pure o gliding to ʊ as in should. Feel the jaw move from open to slightly closed; the tongue is arched in the back and the lips are rounded. The length comes from the first sound.',
    'aʊ': 'As in now. Starts very open on ɑ as in father — the most open vowel in the accent — then the arch in the back of the tongue raises for ʊ. Lips start open and close to a more rounded position. The length comes from the first sound.',
    'ɔɪ': 'As in toy. Starts on the back vowel ɔ as in call and glides to ɪ. Look in the mirror: the tongue arch moves from back to front, the jaw from a wide to a small opening, and the lips from rounded to smiling. The length comes from the first sound.',
    'ɝ': 'Tongue: remove the tip from the lower gum ridge — the tip curls as the r is activated and you should feel tension in the tip. The body of the tongue should not pull back; the middle of the tongue is arched high. Lips: relaxed. Lower jaw: only slightly opened. Used in the stressed syllable (journey, herbal).',
    'ɚ': 'The tongue tip curls but is more relaxed, not as tense as ɝ in serve. Lips relaxed, jaw slightly opened. Short in duration — if this sound is stressed or lengthened the accent will begin to sound unnatural.',
    'ɑɹ': "As in car. The back vowel ɑ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from the lower gum ridge. Don't let the back of the tongue pull back.",
    'ɔɹ': "As in horse. The back vowel ɔ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from the lower gum ridge. Don't let the back of the tongue pull back.",
    'ɛɹ': "As in Claire. The front vowel ɛ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from the lower gum ridge. Don't let the back of the tongue pull back.",
    'ɪɹ': "As in fears. The front vowel ɪ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from the lower gum ridge. Don't let the back of the tongue pull back.",
    'ʊɹ': "As in poor. The back vowel ʊ followed by the schwa with the activated r: curl the tip of the tongue, the tip and blade tense as they raise away from the lower gum ridge. Don't let the back of the tongue pull back.",
    'ɹ': 'As in red. Either the tongue tip raises just behind the upper gum ridge, curled and pointed up to the hard palate without touching it, with the lips rounding — or the back of the tongue raises and retracts, pressing against the upper back teeth, with the tip less active. Use whichever method is best for you.',
    'r': 'As in red. Either the tongue tip raises just behind the upper gum ridge, curled and pointed up to the hard palate without touching it, with the lips rounding — or the back of the tongue raises and retracts, pressing against the upper back teeth, with the tip less active. Use whichever method is best for you.',
    'l': 'As in love. The tip and blade of the tongue make contact with the upper gum ridge and the air passes out at the sides of the tongue. The American l is darker than other accents — imagine the tip and blade pushing forward against the gum ridge as if pushing against a wall. The tip is tense; the rest of the tongue broad, flat and free of tension.',
    't': "As in toast. Fully sounded t: firmly and quickly apply pressure with the tongue tip on the upper gum ridge and let the tip drop back down to the lower gum ridge at the finish. Used at the start of a word, at the beginning of a stressed syllable, and at the end of a word after f, k, l, p or s (draft, halt, pact).",
    'd': 'As in doe. Firmly and quickly apply pressure with the tongue tip on the upper gum ridge, then let the tip drop back down to the lower gum ridge. Voiced.',
    'θ': "As in thin. The tip of the tongue rests between the upper and lower teeth and the air passes through the mouth. Keep the rest of the mouth relaxed and watch that th doesn't sound like d — that happens if the tip pulls back. The tip needs to be between the teeth.",
    'ð': "As in then. The tip of the tongue rests between the upper and lower teeth and you add voice. Keep the rest of the mouth relaxed and watch that th doesn't sound like d — that happens if the tip pulls back. The tip needs to be between the teeth.",
    's': "As in sue. The tip of the tongue is positioned toward the upper gum ridge but doesn't actually touch. Lower jaw relaxed, teeth almost closed. Voiceless.",
    'z': "As in zoo. The tip of the tongue is positioned toward the upper gum ridge but doesn't actually touch. Lower jaw relaxed, teeth almost closed. Voiced.",
    'ʃ': 'As in shoe. The tip is positioned toward the upper gum ridge without touching; feel the sides of the tongue touch the upper teeth as the body of the tongue raises high. Lower jaw relaxed, teeth almost closed. Voiceless.',
    'ʒ': 'As in genre. The tip is positioned toward the upper gum ridge without touching; feel the sides of the tongue touch the upper teeth as the body of the tongue raises high. Lower jaw relaxed, teeth almost closed. Voiced.',
    'tʃ': 'As in chin. The tip makes contact with the upper gum ridge (as for t), then quickly moves to the sh position just behind it without touching — fast enough to sound like one sound. Lower jaw relaxed. Voiceless.',
    'dʒ': 'As in gin. The tip makes contact with the upper gum ridge (as for d), then quickly moves to the zh position just behind it without touching — fast enough to sound like one sound. Lower jaw relaxed. Voiced.',
    'ŋ': 'As in sing. The back of the tongue raises to make contact with the soft palate; as the sound is voiced, let it drop slightly away. The tip stays at the lower gum ridge. Words ending in -ing should be pronounced — avoid the temptation to drop the final g sound.',
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

T_TIPS = {
    "full": TIPS["t"],
    "flap": "In this word the t is lightly voiced — it sounds like d. Firmly and quickly apply pressure with the tongue tip on the upper gum ridge and let it drop back down to the lower gum ridge. This happens after a stressed syllable (matter, water) and between a vowel, r and another vowel (quarter, parting).",
    "held": "In this word the t is held: make the tongue placement for t at the upper gum ridge but don't release the tip back down. This happens before another consonant (football, basketball), after n (internet, twenty) and usually at the end of a word.",
}


def tip_for(expected: str, t_kind: Optional[str] = None) -> Optional[str]:
    if expected == "t" and t_kind:
        return T_TIPS.get(t_kind, TIPS["t"])
    return TIPS.get(expected)


class PhonemeScore(BaseModel):
    expected: str
    score: Optional[float] = None
    azure_score: Optional[float] = None  # Azure's own accuracy score, untouched by the ear
    heard: Optional[str] = None
    status: str  # accurate | close | needs_work | unknown
    start_s: Optional[float] = None
    end_s: Optional[float] = None
    ear: Optional[str] = None  # confirmed | missing | unsure
    ear_p: Optional[float] = None  # ear confidence in the expected sound
    formant: bool = False  # vowel flagged by the formant check
    badge: Optional[str] = None
    tip: Optional[str] = None  # custom tip replacing the sound's standard tip
    note: Optional[str] = None
    flap: bool = False  # American flapped T expected in this slot
    reduced: bool = False  # unstressed ɪ: ə is accepted
    stress: Optional[int] = None  # CMU stress of this vowel (0/1/2)
    t_kind: Optional[str] = None  # full | flap | held (t only)
    azure_expected: Optional[str] = None  # set when Azure picked a non-American variant
    intrusion: bool = False  # extra vowel/glide glued to this sound (ə-u, j-u)


class NeedsWork(BaseModel):
    phoneme: str
    score: Optional[float] = None
    heard: Optional[str] = None
    tip: Optional[str] = None
    confirmed: bool = False  # the ear heard a different sound in this slot
    overdone: bool = False   # sound present but held/leaned on too long
    intrusion: bool = False  # sound present but with an extra vowel/glide glued to it
    badge: Optional[str] = None  # custom label replacing "not heard" (e.g. "too far forward")
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
    """The ear heard a full extra vowel between the expected sounds → an added syllable (alu-MIN-i-um).
    Onglides glued to a vowel (ə-u, j-u) are reported as a sound error instead, not here."""
    if not heard or not out.expected_vowels:
        return
    extra = int(heard.get("extra_nuclei") or 0)
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
R_MAX_FINAL_S = 0.62    # stressed final ɝ/ɹ (word, serve): Hannah runs 0.37–0.61 s
R_MAX_FINAL_UNSTRESSED_S = 0.42  # final ɚ (mother, water) is short by nature: Hannah 0.32–0.41 s
R_REL = 1.25            # or clearly longer than Hannah's own take of this word
R_REL_MIN_S = 0.30
OVERDONE_PENALTY = 10


def _held_r(p: "PhonemeScore", i: int, timed: List["PhonemeScore"], ref: Optional[dict]) -> bool:
    dur = p.end_s - p.start_s
    final = i == len(timed) - 1
    limit = (R_MAX_FINAL_UNSTRESSED_S if p.expected == "ɚ" else R_MAX_FINAL_S) if final else R_MAX_S
    if dur >= limit:
        return True
    ref_ph = (ref or {}).get("phonemes") or []
    if i < len(ref_ph) and ref_ph[i]["expected"] == p.expected and ref_ph[i]["dur"] > 0:
        return dur >= R_REL_MIN_S and dur >= R_REL * ref_ph[i]["dur"]
    return False


def check_held_r(out: "AssessResponse", ref: Optional[dict] = None) -> None:
    """Flag R-coloured sounds the speaker holds too long (Azure phoneme timings vs Hannah's reference take)."""
    timed = [p for p in out.phonemes if p.start_s is not None and p.end_s is not None]
    if not timed:
        return
    hits = []
    for i, p in enumerate(timed):
        if p.expected not in R_SOUNDS or p.ear == "missing":
            continue
        if _held_r(p, i, timed, ref):
            p.status, p.note = "needs_work", "The r was held too long. Pronounce the r but don’t linger on the sound."
            hits.append(p)
    if not hits:
        return
    seen = {n.phoneme for n in out.needs_work}
    for p in hits:
        if p.expected in seen:
            continue
        seen.add(p.expected)
        out.needs_work.append(NeedsWork(phoneme=p.expected, score=p.score, tip=tip_for(p.expected, p.t_kind), overdone=True, note=p.note))
    out.accurate = [a for a in out.accurate if a not in {p.expected for p in hits}]
    out.score = max(0.0, min(float(out.score or 0) - OVERDONE_PENALTY * len({p.expected for p in hits}), MISS_CAP))
    out.band, out.summary = _band(out.score)
    out.score10 = round(out.score / 10, 1)


def _display_pattern(graphemes: List[str], idx: int) -> str:
    return "-".join(g.upper() if i == idx else g.lower() for i, g in enumerate(graphemes))


FORMANT_SKIP_NEXT = {"m", "n", "ŋ", "l", "ɹ", "r", "w", "j"}  # these colour the vowel's formants
FORMANT_TRUST_EAR_P = 0.80   # ear confidence needed before a vowel teaches the speaker scale
FORMANT_JUDGE_EAR_P = 0.60   # below this the formant table gets a say even if the ear said "confirmed"


def vowel_check(out: "AssessResponse", wav_bytes: bytes, profile: dict) -> List[dict]:
    """Second ear for vowels: F1/F2 vs General American targets fitted to this speaker.
    Learns the speaker from vowels the recogniser confirmed; judges the ones it was unsure about.
    Returns admin readings [{expected, f1, f2}]; mutates `profile` in place."""
    readings: List[dict] = []
    scale = formants.speaker_scale(profile)
    own_u = formants.own_u_f2(profile)
    hits: List[PhonemeScore] = []
    for i, p in enumerate(out.phonemes):
        nxt = out.phonemes[i + 1].expected if i + 1 < len(out.phonemes) else ""
        if p.expected not in formants.CHECKED or p.start_s is None or p.end_s is None:
            continue
        coloured = nxt in FORMANT_SKIP_NEXT  # nasal/liquid after the vowel shifts its formants
        point = formants.measure(wav_bytes, p.start_s, p.end_s)
        if not point:
            continue
        readings.append({"expected": p.expected, "f1": round(point[0]), "f2": round(point[1])})
        if p.ear == "missing":
            continue
        trusted = p.ear == "confirmed" and (p.ear_p or 0) >= FORMANT_JUDGE_EAR_P  # a sure recogniser outranks the table…
        # The recogniser folds a fronted ʉ into u and a glided [əi] into i, so these run even when it is sure.
        traj = formants.trajectory(wav_bytes, p.start_s, p.end_s)
        verdict = formants.judge_glide(p.expected, traj) if traj else None
        if not verdict and (not trusted or p.expected == "u"):
            verdict = formants.judge(p.expected, point, scale, strict=coloured, own_u=own_u)
            # A neighbouring-vowel call against a recogniser confirmation (even a weak one) is not worth asserting.
            if verdict and p.ear == "confirmed" and _adjacent(p.expected, verdict.get("heard")):
                verdict = None
        if trusted and (p.ear_p or 0) >= FORMANT_TRUST_EAR_P and not verdict and not coloured:
            formants.profile_add(profile, p.expected, point)  # …but only sure ones teach the speaker scale
        if verdict:
            p.status, p.heard, p.note, p.formant = "needs_work", verdict["heard"], verdict.get("note"), True
            p.badge, p.tip = verdict.get("badge"), verdict.get("tip")
            if p.score is None or p.score > CLOSE_AT - 1:
                p.score = float(CLOSE_AT - 1)
            hits.append(p)
    if hits:
        _flag_sounds(out, hits)
    return readings


def rhotic_check(out: "AssessResponse", wav_bytes: bytes, scale) -> List[dict]:
    """Fourth ear for r-colouring: a rhotic vowel pulls F3 down to ~1.9–2.1 kHz (women); a plain
    vowel keeps it ≥ 2.5 kHz. Catches a non-rhotic ɝ/ɚ the recogniser let through (sɜːv)."""
    readings: List[dict] = []
    hits: List[PhonemeScore] = []
    for p in out.phonemes:
        if p.expected not in R_SOUNDS or p.start_s is None or p.end_s is None or p.ear == "missing":
            continue
        start = p.start_s if p.expected in ("ɝ", "ɚ", "ɹ", "r") else p.start_s + 0.6 * (p.end_s - p.start_s)
        f3 = formants.f3_median(wav_bytes, start, p.end_s)
        if f3 is None:
            continue
        readings.append({"expected": p.expected, "f3": round(f3)})
        if formants.rhotic_missing(f3, scale):
            p.status, p.note = "needs_work", "The r sound wasn't heard."
            p.heard = {"ɝ": "ɜ", "ɚ": "ə"}.get(p.expected, p.expected[0])
            if p.score is None or p.score > CLOSE_AT - 1:
                p.score = float(CLOSE_AT - 1)
            hits.append(p)
    if hits:
        _flag_sounds(out, hits)
    return readings


def _flag_sounds(out: "AssessResponse", hits: List["PhonemeScore"]) -> None:
    """Add measurement-based misses (formant / fricative ears) to the result with the miss penalty."""
    seen = {n.phoneme for n in out.needs_work}
    for p in hits:
        if p.expected in seen:
            for n in out.needs_work:
                if n.phoneme == p.expected:
                    n.confirmed, n.heard, n.note, n.score = True, p.heard, p.note, min(n.score or 100, p.score or 0)
                    n.badge, n.tip = p.badge, p.tip or n.tip
            continue
        seen.add(p.expected)
        out.needs_work.append(NeedsWork(phoneme=p.expected, score=p.score, heard=p.heard, tip=p.tip or tip_for(p.expected),
                                        confirmed=True, note=p.note, badge=p.badge))
    out.needs_work.sort(key=lambda n: (not (n.confirmed or n.intrusion), n.score or 0))
    out.accurate = [a for a in out.accurate if a not in {p.expected for p in hits}]
    out.score = max(0.0, min(float(out.score or 0) - MISS_PENALTY * len({p.expected for p in hits}), MISS_CAP))
    out.band, out.summary = _band(out.score)
    out.score10 = round(out.score / 10, 1)


def fricative_check(out: "AssessResponse", wav_bytes: bytes) -> List[dict]:
    """Third ear: sibilance and voicing of s z ʃ ʒ f v θ ð from the noise frames of each window."""
    readings: List[dict] = []
    hits: List[PhonemeScore] = []
    last = len(out.phonemes) - 1
    for i, p in enumerate(out.phonemes):
        if p.expected not in fricatives.CHECKED or p.start_s is None or p.end_s is None or p.ear == "missing":
            continue
        m = fricatives.measure(wav_bytes, p.start_s, p.end_s)
        if not m:
            continue
        readings.append({"expected": p.expected, **m})
        verdict = fricatives.judge(p.expected, m, i == last)
        if verdict:
            p.status, p.heard, p.note = "needs_work", verdict["heard"], verdict["note"]
            if p.score is None or p.score > CLOSE_AT - 1:
                p.score = float(CLOSE_AT - 1)
            hits.append(p)
    if hits:
        _flag_sounds(out, hits)
    return readings


def stress_check(word: str, syllables: List[dict], wav_bytes: bytes) -> Optional[StressCheck]:
    """Compare the loudest/longest syllable with the CMU primary stress. Conservative:
    only 'wrong' when another syllable is clearly louder AND not shorter."""
    phones = get_arpabet(word) or []
    stresses = [ph[-1] for ph in phones if ph[-1].isdigit()]
    if len(stresses) < 2 or len(stresses) != len(syllables) or "1" not in stresses:
        return None
    expected = stresses.index("1")
    import io
    import wave
    import numpy as np
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        sr = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
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
EAR_SURE_P = 0.90   # ear confidence that overrides an Azure "close" (60–79) hedge
# Neighbouring vowels the ear mishears on some voices (Hannah's ɛ→æ, æ→ɑ): a swap between these
# is only asserted when Azure also doubted the sound.
ADJACENT_VOWELS = {("ɛ", "æ"), ("æ", "ɑ"), ("ɪ", "i"), ("ʊ", "u"), ("ʌ", "ɑ"), ("ɔ", "oʊ"), ("ʊ", "ə"), ("æ", "ʌ"), ("æ", "ə"),
                   ("tʃ", "ʃ"), ("dʒ", "ʒ"), ("dʒ", "j")}  # affricate/fricative too: the ear drops the stop onset
ADJACENT_AZURE_OK = 80


def _adjacent(expected: str, heard: Optional[str]) -> bool:
    return bool(heard) and ((expected, heard) in ADJACENT_VOWELS or (heard, expected) in ADJACENT_VOWELS)


def apply_ear(out: "AssessResponse", heard: Optional[dict]) -> None:
    """Fold the recogniser's per-window verdicts into the Azure-based result."""
    if not heard:
        return
    checks = heard.get("checks") or []
    for p, c in zip(out.phonemes, checks):
        p.ear = c.get("verdict")
        p.ear_p = c.get("p_expected")
        if c["verdict"] == "confirmed" and p.status == "close" and (c.get("p_expected") or 0) >= EAR_SURE_P:
            p.status = "accurate"  # Azure hedged, the ear clearly heard the sound: don't nag
            out.needs_work = [n for n in out.needs_work if n.phoneme != p.expected or any(
                q.expected == p.expected and q.status in ("close", "needs_work") for q in out.phonemes if q is not p)]
        if c["verdict"] == "missing" and not c.get("intrusion") and _adjacent(p.expected, c.get("heard")) \
                and (p.azure_score or 0) >= ADJACENT_AZURE_OK:
            p.ear = "unsure"
            continue
        if c["verdict"] == "missing":
            p.status = "needs_work"
            p.heard = c.get("heard") or p.heard
            p.note = c.get("note")
            p.intrusion = bool(c.get("intrusion"))
            p.badge = "glided" if c.get("glided") else None
            if p.score is None or p.score > CLOSE_AT - 1:
                p.score = float(CLOSE_AT - 1)
    misses = [p for p in out.phonemes if p.ear == "missing"]
    out.accurate = sorted({p.expected for p in out.phonemes if p.status == "accurate" and p.ear != "missing"})
    if misses:
        distinct = {p.expected for p in misses}
        out.score = max(0.0, min(float(out.score or 0) - MISS_PENALTY * len(distinct), MISS_CAP))
        out.band, out.summary = _band(out.score)
        seen = {n.phoneme for n in out.needs_work}
        for p in misses:
            if p.expected in seen:
                for n in out.needs_work:
                    if n.phoneme == p.expected:
                        n.confirmed, n.intrusion, n.badge = not p.intrusion, p.intrusion, p.badge
                        n.heard, n.score, n.note = p.heard or n.heard, min(n.score or 100, p.score or 0), p.note
                continue
            seen.add(p.expected)
            out.needs_work.append(NeedsWork(phoneme=p.expected, score=p.score, heard=p.heard, tip=tip_for(p.expected, p.t_kind),
                                            confirmed=not p.intrusion, intrusion=p.intrusion, note=p.note, badge=p.badge))
        out.needs_work.sort(key=lambda n: (not (n.confirmed or n.intrusion), n.score or 0))
    out.score10 = round((out.score or 0) / 10, 1)


def enabled() -> bool:
    """Needs the Azure key AND an ear: the preview side-venv worker, or the hosted ear service
    (EAR_URL + EAR_SECRET, see ear-service/README.md). PRACTICE_MODE=force skips the ear check."""
    mode = os.environ.get("PRACTICE_MODE", "").lower()
    has_key = bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"))
    if not has_key:
        return False
    if mode == "force":
        return True
    return mode == "on" and (bool(ear.EAR_URL) or os.path.exists(ear.EAR_PYTHON))


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
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(url, params=params, headers=headers, content=wav)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="The pronunciation checker took too long. Please try again.")
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="The pronunciation checker is unreachable right now. Please try again shortly.")
        if r.status_code == 200 or attempt == 2:
            break
        # The speech tier returns sporadic 401/429s under back-to-back requests; they clear within seconds.
        logger.warning("Azure speech %s on attempt %d: %s — retrying", r.status_code, attempt + 1, r.text[:200])
        await asyncio.sleep(1.5 * (attempt + 1))
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


def t_kinds(word: str, azure_phonemes: List[str]) -> List[Optional[str]]:
    """Classify each Azure 't' slot as full / flap / held using CMU stress marks (All American Voice rules).

    Falls back to None when the T counts don't line up.
    """
    phones = get_arpabet(word) or []
    kinds_cmu: List[str] = []
    for i, ph in enumerate(phones):
        if ph != "T":
            continue
        prev = phones[i - 1] if i > 0 else ""
        nxt = phones[i + 1] if i + 1 < len(phones) else ""
        prev_v = prev[:2] in _ARPA_VOWELS
        nxt_v = nxt[:2] in _ARPA_VOWELS
        if (prev_v or prev == "R") and ((nxt_v and nxt.endswith("0")) or nxt == "L"):
            kinds_cmu.append("flap")
        elif not nxt:
            kinds_cmu.append("full" if prev in ("F", "K", "L", "P", "S") else "held")
        elif prev == "N" or (nxt and not nxt_v):
            kinds_cmu.append("held")
        else:
            kinds_cmu.append("full")
    t_slots = [i for i, p in enumerate(azure_phonemes) if p == "t"]
    out: List[Optional[str]] = [None] * len(azure_phonemes)
    if len(t_slots) != len(kinds_cmu):
        return out
    for slot, k in zip(t_slots, kinds_cmu):
        out[slot] = k
    return out


def reduced_i_slots(word: str, azure_phonemes: List[str]) -> List[bool]:
    """Mark ɪ slots that CMU has unstressed (IH0): Americans say those as ə, so ə must be accepted."""
    phones = get_arpabet(word) or []
    cmu = [ph.endswith("0") for ph in phones if ph[:2] == "IH"]
    slots = [i for i, p in enumerate(azure_phonemes) if p == "ɪ"]
    out = [False] * len(azure_phonemes)
    if len(slots) != len(cmu):
        return out
    for slot, r in zip(slots, cmu):
        out[slot] = r
    return out


def vowel_stress_slots(word: str, azure_phonemes: List[str]) -> List[Optional[int]]:
    """CMU stress (0/1/2) for each vowel slot, in order; None everywhere if the counts don't line up."""
    phones = get_arpabet(word) or []
    cmu = [int(ph[-1]) for ph in phones if ph[:2] in _ARPA_VOWELS and ph[-1].isdigit()]
    vowel_syms = ear.EXPECTED_VOWELS | {"ɝ", "ɚ"}
    slots = [i for i, p in enumerate(azure_phonemes) if p in vowel_syms]
    out: List[Optional[int]] = [None] * len(azure_phonemes)
    if len(slots) != len(cmu):
        return out
    for slot, st in zip(slots, cmu):
        out[slot] = st
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
                expected=exp, score=sc, azure_score=sc, heard=heard, status=st,
                start_s=(p.get("Offset") or 0) / 1e7 if p.get("Offset") is not None else None,
                end_s=((p.get("Offset") or 0) + (p.get("Duration") or 0)) / 1e7 if p.get("Offset") is not None else None,
            ))
        for ps, kind in zip(w_phonemes, t_kinds(word_text, [ps.expected for ps in w_phonemes])):
            ps.t_kind = kind
            ps.flap = kind == "flap"
        # Azure accepts any dictionary variant (PROH-cess); we insist on the app's American one.
        phones = our_phones(word_text.lower())
        expected_vowels += sum(1 for ph in phones if ph.rstrip("012") in _ARPA_VOWELS)
        for ps, ours in zip(w_phonemes, align_expected(expected_sequence(phones), [p.expected for p in w_phonemes])):
            if ours and ours in ear.EXPECTED:
                ps.azure_expected, ps.expected = ps.expected, ours
        for ps, reduced in zip(w_phonemes, reduced_i_slots(word_text, [ps.expected for ps in w_phonemes])):
            ps.reduced = reduced
        for ps, st in zip(w_phonemes, vowel_stress_slots(word_text, [ps.expected for ps in w_phonemes])):
            ps.stress = st
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
            needs.append(NeedsWork(phoneme=p.expected, score=p.score, heard=p.heard, tip=tip_for(p.expected, p.t_kind)))
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

    async def _reference_profile(norm: str) -> Optional[dict]:
        """Hannah's cached clip for this word, timed by Azure once and kept (phoneme durations)."""
        cached = await db.practice_ref.find_one({"word": norm}, {"_id": 0})
        if cached:
            return cached if cached.get("phonemes") else None
        clip = await db.audio_cache.find_one({"word": norm, "manual_override": True}, {"_id": 0, "audio_b64": 1}) \
            or await db.audio_cache.find_one({"word": {"$in": [norm, f"{norm}#ph"]}}, {"_id": 0, "audio_b64": 1})
        if not clip or not clip.get("audio_b64"):
            return None
        profile = {"word": norm, "phonemes": []}
        try:
            with tempfile.TemporaryDirectory(prefix="pt-ref-") as d:
                src, wav = Path(d) / "ref.bin", Path(d) / "ref.wav"
                src.write_bytes(base64.b64decode(clip["audio_b64"]))
                await asyncio.to_thread(_to_wav, src, wav)
                ref = _interpret(norm, await _call_azure(wav.read_bytes(), norm))
            if ref.assessable:
                profile["phonemes"] = [{"expected": p.expected, "dur": round((p.end_s or 0) - (p.start_s or 0), 3)} for p in ref.phonemes]
        except Exception as exc:  # noqa: BLE001
            logger.warning("reference profile for %r failed: %s", norm, exc)
            return None
        await db.practice_ref.update_one({"word": norm}, {"$set": profile}, upsert=True)
        return profile if profile["phonemes"] else None

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
        rate_limit(f"practice:{actor.email}", 600 if is_admin_email(actor.email) else 40, 3600)

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
            windows = [{"expected": p.expected, "start_s": p.start_s or 0.0, "end_s": p.end_s or 0.0, "flap": p.flap, "reduced": p.reduced, "stress": p.stress} for p in out.phonemes]
            try:
                heard = await asyncio.to_thread(ear.listen, wav_bytes, windows)
            except Exception as exc:  # noqa: BLE001
                logger.warning("phoneme ear failed: %s", exc)
            apply_ear(out, heard)
            check_extra_syllables(out, heard)
        if out.assessable:
            want_ref = any(p.expected in R_SOUNDS for p in out.phonemes) or is_admin_email(actor.email)
            ref = await _reference_profile(norm) if want_ref else None
            check_held_r(out, ref)
            user_doc = await db.users.find_one({"email": actor.email}, {"_id": 0, "formant_profile": 1}) or {}
            profile = user_doc.get("formant_profile") or {}
            try:
                readings = await asyncio.to_thread(vowel_check, out, wav_bytes, profile)
                fric = await asyncio.to_thread(fricative_check, out, wav_bytes)
                rho = await asyncio.to_thread(rhotic_check, out, wav_bytes, formants.speaker_scale(profile))
            except Exception as exc:  # noqa: BLE001
                logger.warning("formant/fricative check failed: %s", exc)
                readings, fric, rho = [], [], []
            if profile:
                await db.users.update_one({"email": actor.email}, {"$set": {"formant_profile": profile}})
        else:
            ref, readings, fric, rho, profile = None, [], [], [], {}
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
            ref_ph = (ref or {}).get("phonemes") or []
            timing = [{"expected": p.expected, "dur": round((p.end_s or 0) - (p.start_s or 0), 2),
                       "ref": ref_ph[i]["dur"] if i < len(ref_ph) and ref_ph[i]["expected"] == p.expected else None}
                      for i, p in enumerate(out.phonemes)]
            out.ear = {**ear.status(), "heard": (heard or {}).get("heard"), "checks": (heard or {}).get("checks"),
                       "extra_nuclei": (heard or {}).get("extra_nuclei"), "timing": timing, "formants": readings, "fricatives": fric, "rhotic": rho,
                       "speaker_scale": [round(x, 2) for x in (formants.speaker_scale(profile) or ())],
                       "own_u_f2": round(formants.own_u_f2(profile) or 0) or None}
        await consume_trial(db, actor)
        if not actor.is_subscriber and out.assessable:
            await db.users.update_one({"email": actor.email}, {"$addToSet": {"practice_words": norm}})
            out.trial_locked = True
        return out

    return router
