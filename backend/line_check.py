"""Line self-check: after ElevenLabs renders a scripted line we transcribe it
back (OpenAI whisper-1 via the Emergent key) and compare with the script.
Bad takes (a swapped/dropped/echoed word) are re-rendered — the voice
settings never change, so delivery stays identical; only the bad take goes.
"""
import asyncio
import difflib
import io
import logging
import os
import re
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_RENDERS = 2            # 1 render + 1 retry (user choice: keep credits low)
STT_TIMEOUT_SECONDS = 12

_CONTRACTIONS = {
    "you've": "you have", "i've": "i have", "we've": "we have", "they've": "they have",
    "you're": "you are", "we're": "we are", "they're": "they are",
    "i'm": "i am", "it's": "it is", "that's": "that is", "there's": "there is",
    "he's": "he is", "she's": "she is", "what's": "what is", "who's": "who is",
    "here's": "here is", "let's": "let us",
    "don't": "do not", "doesn't": "does not", "didn't": "did not", "can't": "cannot",
    "won't": "will not", "wouldn't": "would not", "couldn't": "could not",
    "shouldn't": "should not", "isn't": "is not", "aren't": "are not",
    "wasn't": "was not", "weren't": "were not", "haven't": "have not",
    "hasn't": "has not", "hadn't": "had not",
    "i'll": "i will", "you'll": "you will", "we'll": "we will", "he'll": "he will",
    "she'll": "she will", "they'll": "they will", "it'll": "it will",
    "i'd": "i would", "you'd": "you would", "he'd": "he would", "she'd": "she would",
    "we'd": "we would", "they'd": "they would",
    "gonna": "going to", "wanna": "want to", "gotta": "got to",
    "ok": "okay", "mr": "mister", "mrs": "missus", "dr": "doctor",
    "alright": "all right", "til": "until", "till": "until", "cause": "because",
    "yeah": "yes", "yep": "yes", "yup": "yes", "nah": "no",
}

_STT_SOFT = {"um", "uh", "hmm", "mm", "mhm", "ah", "oh", "huh", "hm"}  # STT noise
# Contracted auxiliaries ('d, 'll, 've, 's) are acoustically tiny; STT often
# drops them ("we'd die" → "we die"). Forgive them when missing, never when
# they replace another word.
_SOFT_DELETE = {"would", "will", "have", "had", "is", "are", "am", "us", "shall"}


def _tokens(text: str) -> List[str]:
    text = (text or "").lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"\((?:[^()]*)\)", " ", text)          # (parentheticals) aren't spoken
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)
    out: List[str] = []
    for w in words:
        w = _CONTRACTIONS.get(w, w)
        out.extend(w.split())
    return out


def _is_soft(tok: str) -> bool:
    return tok in _STT_SOFT or len(tok) <= 1 or any(ch.isdigit() for ch in tok)


def _phones(word: str) -> Optional[str]:
    try:
        from phonetics import get_arpabet
        p = get_arpabet(word)
    except Exception:  # noqa: BLE001
        return None
    return " ".join(re.sub(r"\d", "", x) for x in p) if p else None


def _skeleton(word: str) -> str:
    return re.sub(r"[aeiouy]", "", word).replace("ck", "k").replace("ph", "f")


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    if any(ch.isdigit() for ch in a + b):       # "12" vs "twelve" etc.
        return True
    if a.rstrip("s") == b.rstrip("s") and len(a) > 3:   # plural/agreement drift
        return True
    pa, pb = _phones(a), _phones(b)
    if pa and pb and pa == pb:                  # homophones: Abbie/Abby, counsellor/counselor
        return True
    if len(a) >= 4 and len(b) >= 4 and _skeleton(a) == _skeleton(b):  # Leila/Layla spelling drift
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85  # theatre/theater


def mismatches(script: str, heard: str) -> List[Tuple[str, List[str], List[str]]]:
    """Word-level differences that matter: (op, script_words, heard_words)."""
    s, h = _tokens(script), _tokens(heard)
    if not s:
        return []
    out = []
    sm = difflib.SequenceMatcher(None, s, h, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        sw, hw = s[i1:i2], h[j1:j2]
        if op == "replace" and _same("".join(sw), "".join(hw)):   # open-minded / openminded
            continue
        if op == "replace" and len(sw) == len(hw) and all(_same(a, b) for a, b in zip(sw, hw)):
            continue
        if op == "insert" and all(_is_soft(t) for t in hw):
            continue
        if op == "delete" and all(_is_soft(t) or t in _SOFT_DELETE for t in sw):
            continue
        if op == "replace" and all(_is_soft(t) for t in sw + hw):
            continue
        out.append((op, sw, hw))
    return out


def line_matches(script: str, heard: str) -> bool:
    return not mismatches(script, heard)


async def transcribe(audio_bytes: bytes) -> Optional[str]:
    """whisper-1 transcript of an MP3 buffer, or None if STT is unavailable."""
    key = os.environ.get("EMERGENT_LLM_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key or not audio_bytes:
        return None
    try:
        from emergentintegrations.llm.openai import OpenAISpeechToText
        stt = OpenAISpeechToText(api_key=key)
        buf = io.BytesIO(audio_bytes)
        buf.name = "line.mp3"
        resp = await asyncio.wait_for(
            stt.transcribe(file=buf, model="whisper-1", response_format="json",
                           language="en", temperature=0.0),
            timeout=STT_TIMEOUT_SECONDS,
        )
        return (getattr(resp, "text", None) or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("line self-check STT unavailable: %s", str(exc)[:160])
        return None


def _proper_nouns(text: str) -> set:
    """Capitalised words that aren't sentence-initial — names STT may respell."""
    out = set()
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        for w in re.findall(r"[A-Za-z][a-z']*", sent)[1:]:
            if w[0].isupper():
                out.add(w.lower().replace("'", ""))
    return out


def looks_like_stt_bias(text: str, bad: List[Tuple[str, List[str], List[str]]]) -> bool:
    """True only when every disputed script word is a name (Abbie/Abby); a
    repeated glitch on ordinary words ("couple you've years") is a bad take."""
    names = _proper_nouns(text)
    words = [w for _, sw, _ in bad for w in sw]
    return bool(words) and all(w.replace("'", "") in names for w in words)


async def render_verified(text: str, render: Callable[[], Awaitable[bytes]],
                          max_renders: int = MAX_RENDERS) -> Tuple[bytes, Dict]:
    """Render → listen back → re-render on a bad take (up to max_renders).
    Returns (audio, report). If STT is unavailable the first take is used."""
    best: Optional[bytes] = None
    best_bad = 10 ** 6
    last_sig = None
    report: Dict = {"renders": 0, "verified": False, "heard": None}
    for attempt in range(1, max_renders + 1):
        audio = await render()
        report["renders"] = attempt
        if not audio:
            continue
        heard = await transcribe(audio)
        if heard is None:                       # STT down: don't block playback
            report["heard"] = None
            report["stt_unavailable"] = True
            return audio, report
        bad = mismatches(text, heard)
        if not bad:
            report.update(verified=True, heard=heard)
            return audio, report
        logger.info("line self-check: take %d rejected for %r — heard %r (%s)",
                    attempt, text[:60], heard[:80],
                    "; ".join(f"{op} {' '.join(a)!r}->{' '.join(b)!r}" for op, a, b in bad))
        if len(bad) < best_bad:
            best, best_bad = audio, len(bad)
            report["heard"] = heard
        sig = repr(bad)
        if sig == last_sig and looks_like_stt_bias(text, bad):   # same name respelled twice
            report["stt_bias"] = True
            break
        last_sig = sig
    report["gave_up"] = True
    return best or b"", report
