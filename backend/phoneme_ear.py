"""The "ear": an open phoneme recogniser (wav2vec2, LJSpeech/gruut IPA) that reports
what sounds were actually heard inside the time windows Azure gives us.

Only two outcomes are asserted: 'confirmed' (expected sound clearly present) and
'missing' (expected sound essentially absent AND another sound clearly present).
Everything else is 'unsure' and is never shown to students.
"""
import io
import logging
import os
import threading
from typing import List, Optional

logger = logging.getLogger("ear")

MODEL_ID = os.environ.get("PHONEME_EAR_MODEL", "bookbot/wav2vec2-ljspeech-gruut")
FRAME_S = 0.02          # wav2vec2 CTC frame stride
PAD_S = 0.06            # widen each Azure window by this on both sides
CONFIRM_P = 0.5
MISSING_P = 0.10
OTHER_P = 0.60

# Azure en-US IPA symbol → list of requirements; each requirement is a set of
# model tokens any of which satisfies it. Near-merged pairs are allowed.
_R = {"ɹ", "ɚ"}
EXPECTED = {
    "ɑɹ": [{"ɑ", "ɔ", "ʌ"}, _R], "ɔɹ": [{"ɔ", "oʊ", "ɑ"}, _R], "ɛɹ": [{"ɛ", "eɪ", "æ"}, _R],
    "ɪɹ": [{"ɪ", "i"}, _R], "ʊɹ": [{"ʊ", "u", "ɔ"}, _R], "ɝ": [_R], "ɚ": [_R], "ɹ": [_R], "r": [_R],
    "ɑ": [{"ɑ", "ɔ"}], "ɔ": [{"ɔ", "ɑ"}], "ʌ": [{"ʌ", "ə"}], "ə": [{"ə", "ʌ", "ɪ"}],
    "æ": [{"æ"}], "ɛ": [{"ɛ"}], "ɪ": [{"ɪ"}], "i": [{"i"}], "ʊ": [{"ʊ"}], "u": [{"u"}],
    "eɪ": [{"eɪ"}], "aɪ": [{"aɪ"}], "oʊ": [{"oʊ"}], "aʊ": [{"aʊ"}], "ɔɪ": [{"ɔɪ"}],
    "t": [{"t", "d"}], "d": [{"d", "t"}], "p": [{"p"}], "b": [{"b"}], "k": [{"k"}], "ɡ": [{"ɡ"}], "g": [{"ɡ"}],
    "f": [{"f"}], "v": [{"v"}], "θ": [{"θ"}], "ð": [{"ð"}], "s": [{"s"}], "z": [{"z"}], "ʃ": [{"ʃ"}], "ʒ": [{"ʒ"}],
    "tʃ": [{"t͡ʃ"}], "dʒ": [{"d͡ʒ"}], "h": [{"h"}], "m": [{"m"}], "n": [{"n"}], "ŋ": [{"ŋ"}],
    "l": [{"l"}], "w": [{"w"}], "j": [{"j"}],
}
# Tokens that are never reported as a competing sound.
_IGNORE = {"|", "[UNK]", "[PAD]", "<s>", "</s>"}

_state = {"model": None, "proc": None, "status": "idle", "error": None}


def status() -> dict:
    return {"model": MODEL_ID, "status": _state["status"], "error": _state["error"]}


def available() -> bool:
    return _state["model"] is not None


def _load() -> None:
    try:
        _state["status"] = "loading"
        import torch  # noqa: F401
        from transformers import AutoModelForCTC, AutoProcessor
        proc = AutoProcessor.from_pretrained(MODEL_ID)
        model = AutoModelForCTC.from_pretrained(MODEL_ID).eval()
        _state.update(proc=proc, model=model, status="ready", error=None)
        logger.info("phoneme ear ready (%s)", MODEL_ID)
    except Exception as exc:  # noqa: BLE001
        _state.update(status="error", error=str(exc)[:300])
        logger.warning("phoneme ear unavailable: %s", exc)


def warm() -> None:
    """Load the model in a background thread (no-op if disabled or already loading)."""
    if os.environ.get("PHONEME_EAR", "on").lower() in ("0", "off", "false") or _state["status"] != "idle":
        return
    threading.Thread(target=_load, name="phoneme-ear-load", daemon=True).start()


def _posteriors(wav_bytes: bytes):
    import soundfile as sf
    import torch
    audio, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    proc, model = _state["proc"], _state["model"]
    inputs = proc(audio, sampling_rate=sr, return_tensors="pt")
    with torch.no_grad():
        logits = model(**inputs).logits[0]
    probs = torch.softmax(logits, dim=-1).numpy()
    ids = probs.argmax(axis=-1)
    heard = proc.batch_decode(ids[None, :])[0]
    vocab = proc.tokenizer.get_vocab()
    id2tok = {i: t for t, i in vocab.items() if isinstance(i, int) and i < probs.shape[1]}
    return probs, id2tok, heard


def _check_window(probs, id2tok, start_s: float, end_s: float, expected: str, exclude: set) -> dict:
    reqs = EXPECTED.get(expected)
    if not reqs:
        return {"expected": expected, "verdict": "unsure", "p_expected": None, "heard": None}
    a = max(0, int((start_s - PAD_S) / FRAME_S))
    b = min(len(probs), int((end_s + PAD_S) / FRAME_S) + 1)
    if b <= a:
        return {"expected": expected, "verdict": "unsure", "p_expected": None, "heard": None}
    seg = probs[a:b]
    accept = set().union(*reqs)
    # Weakest requirement decides (e.g. for /ɑɹ/ the R part).
    req_p = [float(seg[:, [i for i, t in id2tok.items() if t in req]].max()) for req in reqs]
    p_exp = min(req_p)
    failing = reqs[req_p.index(p_exp)]
    other_tok, other_p = None, 0.0      # display candidate (neighbouring sounds excluded)
    any_other_p = 0.0                   # decision evidence (anything but the expected sound)
    for i, t in id2tok.items():
        if t in accept or t in _IGNORE:
            continue
        p = float(seg[:, i].max())
        any_other_p = max(any_other_p, p)
        if t in exclude:
            continue
        if p > other_p:
            other_tok, other_p = t, p
    vowel_ok = len(reqs) > 1 and req_p[0] >= CONFIRM_P
    if p_exp >= CONFIRM_P:
        verdict = "confirmed"
    elif p_exp < MISSING_P and (any_other_p >= OTHER_P or vowel_ok):
        verdict = "missing"
    else:
        verdict = "unsure"
    note = None
    if verdict == "missing" and failing is _R and len(reqs) > 1:
        note = "The R wasn't heard — the vowel was there but not the American R after it."
        vowel = max(((float(seg[:, i].max()), t) for i, t in id2tok.items() if t in reqs[0]), default=(0.0, None))
        other_tok = vowel[1] or other_tok
    elif verdict == "missing" and failing is _R:
        note = "The R wasn't heard."
    return {"expected": expected, "verdict": verdict, "p_expected": round(p_exp, 2),
            "heard": other_tok.replace("͡", "") if other_tok and verdict != "confirmed" else None,
            "p_heard": round(other_p, 2), "note": note}


def listen(wav_bytes: bytes, windows: List[dict]) -> Optional[dict]:
    """windows: [{expected, start_s, end_s}] from Azure phoneme timings (16 kHz mono PCM wav)."""
    if not available():
        return None
    probs, id2tok, heard = _posteriors(wav_bytes)
    checks = []
    for i, w in enumerate(windows):
        neighbours = set()
        for j in (i - 1, i + 1):
            if 0 <= j < len(windows):
                neighbours |= set().union(*EXPECTED.get(windows[j]["expected"], []))
        checks.append(_check_window(probs, id2tok, w["start_s"], w["end_s"], w["expected"], neighbours))
    return {"heard": heard, "checks": checks}
