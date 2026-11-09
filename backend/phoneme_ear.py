"""The "ear": an open phoneme recogniser (wav2vec2, LJSpeech/gruut IPA) that reports
what sounds were actually heard inside the time windows Azure gives us.

Only two outcomes are asserted: 'confirmed' (expected sound clearly present) and
'missing' (expected sound essentially absent AND another sound clearly present).
Everything else is 'unsure' and is never shown to students.
"""
import base64
import io
import json
import logging
import os
import threading
from typing import List, Optional

logger = logging.getLogger("ear")

MODEL_ID = os.environ.get("PHONEME_EAR_MODEL", "vitouphy/wav2vec2-xls-r-300m-timit-phoneme")
INT8 = False
DTYPE = os.environ.get("PHONEME_EAR_DTYPE", "bfloat16")  # bf16 halves RAM (~600 MB) with identical readouts
FRAME_S = 0.02          # wav2vec2 CTC frame stride
PAD_S = 0.06            # widen each Azure window by this on both sides
CONFIRM_P = 0.5
MISSING_P = 0.10
OTHER_P = 0.60

# Azure en-US IPA symbol → list of requirements; each requirement is a set of
# model tokens (TIMIT 39-phone set) any of which satisfies it. TIMIT folds
# ɔ→ɑ, ʌ→ə, ɚ→ɝ, ʒ→ʃ, so those merges are built in.
_R = {"ɹ", "ɝ"}
_FLAP = {"ɾ", "d"}
EXPECTED = {
    "ɑɹ": [{"ɑ"}, _R], "ɔɹ": [{"ɑ", "oʊ"}, _R], "ɛɹ": [{"ɛ", "eɪ", "æ"}, _R],
    "ɪɹ": [{"ɪ", "i"}, _R], "ʊɹ": [{"ʊ", "u", "ɑ"}, _R], "ɝ": [_R], "ɚ": [_R], "ɹ": [_R], "r": [_R],
    "ɑ": [{"ɑ"}], "ɔ": [{"ɑ"}], "ʌ": [{"ə"}], "ə": [{"ə", "ɪ"}],
    "æ": [{"æ"}], "ɛ": [{"ɛ"}], "ɪ": [{"ɪ"}], "i": [{"i"}], "ʊ": [{"ʊ"}], "u": [{"u"}],
    "eɪ": [{"eɪ"}], "aɪ": [{"aɪ"}], "oʊ": [{"oʊ"}], "aʊ": [{"aʊ"}], "ɔɪ": [{"ɔɪ"}],
    "t": [{"t"}], "d": [{"d", "ɾ"}], "p": [{"p"}], "b": [{"b"}], "k": [{"k"}], "ɡ": [{"g"}], "g": [{"g"}],
    "f": [{"f"}], "v": [{"v"}], "θ": [{"θ"}], "ð": [{"ð"}], "s": [{"s"}], "z": [{"z"}], "ʃ": [{"ʃ"}], "ʒ": [{"ʃ", "z"}],
    "tʃ": [{"ʧ"}], "dʒ": [{"ʤ"}], "h": [{"h"}], "m": [{"m", "n"}], "n": [{"n", "m"}], "ŋ": [{"ŋ", "n"}],
    "l": [{"l"}], "w": [{"w"}], "j": [{"j"}],
}
FLAP_REQ = [_FLAP]  # an American flapped T: heard as a quick D / tap
DISPLAY = {"ʧ": "tʃ", "ʤ": "dʒ", "ɾ": "flap t", "g": "ɡ"}
# Tokens that are never reported as a competing sound.
_IGNORE = {"|", " ", "[UNK]", "[PAD]", "<s>", "</s>"}

_state = {"model": None, "proc": None, "status": "idle", "error": None}
_worker = {"proc": None, "lock": threading.Lock()}
EAR_PYTHON = os.environ.get("EAR_PYTHON", "/opt/ear-venv/bin/python")


def status() -> dict:
    return {"model": MODEL_ID, "status": _state["status"], "error": _state["error"]}


def available() -> bool:
    return _state["model"] is not None or (_worker["proc"] is not None and _state["status"] == "ready")


def _start_worker() -> None:
    """Spawn the side-venv worker and wait for its ready line."""
    import subprocess
    try:
        _state["status"] = "loading"
        proc = subprocess.Popen(
            [EAR_PYTHON, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ear_worker.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        first = json.loads(proc.stdout.readline() or "{}")
        if first.get("ready"):
            _worker["proc"] = proc
            _state.update(status="ready", error=None)
            logger.info("phoneme ear ready via worker (%s)", MODEL_ID)
        else:
            proc.kill()
            _state.update(status="error", error=first.get("error") or "worker failed to load")
            logger.warning("phoneme ear worker failed: %s", _state["error"])
    except Exception as exc:  # noqa: BLE001
        _state.update(status="error", error=str(exc)[:300])
        logger.warning("phoneme ear worker unavailable: %s", exc)


def _ask_worker(wav_bytes: bytes, windows: List[dict]) -> Optional[dict]:
    proc = _worker["proc"]
    if proc is None or proc.poll() is not None:
        _worker["proc"] = None
        _state.update(status="error", error="worker exited")
        return None
    req = json.dumps({"wav_b64": base64.b64encode(wav_bytes).decode(), "windows": windows})
    with _worker["lock"]:
        proc.stdin.write(req + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
    out = json.loads(line or "{}")
    if out.get("error"):
        logger.warning("phoneme ear worker error: %s", out["error"])
        return None
    return out or None


def _load() -> None:
    try:
        _state["status"] = "loading"
        import torch
        from transformers import AutoModelForCTC, AutoProcessor
        torch.set_num_threads(2)
        proc = AutoProcessor.from_pretrained(MODEL_ID)
        model = AutoModelForCTC.from_pretrained(MODEL_ID, dtype=DTYPE).eval()
        _state.update(proc=proc, model=model, status="ready", error=None)
        logger.info("phoneme ear ready (%s, %s)", MODEL_ID, DTYPE)
    except Exception as exc:  # noqa: BLE001
        _state.update(status="error", error=str(exc)[:300])
        logger.warning("phoneme ear unavailable: %s", exc)


def warm() -> None:
    """Load the model in a background thread (no-op if disabled or already loading).
    Uses the side-venv worker when present so the main env stays ML-free."""
    if os.environ.get("PHONEME_EAR", "on").lower() in ("0", "off", "false") or _state["status"] != "idle":
        return
    target = _start_worker if os.path.exists(EAR_PYTHON) else _load
    threading.Thread(target=target, name="phoneme-ear-load", daemon=True).start()


def _posteriors(wav_bytes: bytes):
    import soundfile as sf
    import torch
    audio, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    proc, model = _state["proc"], _state["model"]
    inputs = proc(audio, sampling_rate=sr, return_tensors="pt")
    dtype = next(model.parameters()).dtype
    inputs = {k: (v.to(dtype) if v.is_floating_point() else v) for k, v in inputs.items()}
    with torch.inference_mode():
        logits = model(**inputs).logits[0].float()
    probs = torch.softmax(logits, dim=-1).numpy()
    ids = probs.argmax(axis=-1)
    heard = proc.batch_decode(ids[None, :])[0]
    vocab = proc.tokenizer.get_vocab()
    id2tok = {i: t for t, i in vocab.items() if isinstance(i, int) and i < probs.shape[1]}
    pad = proc.tokenizer.pad_token_id
    tokens, prev = [], None
    for i in ids.tolist():
        if i != prev and i != pad and id2tok.get(i) not in _IGNORE:
            tokens.append(id2tok[i])
        prev = i
    return probs, id2tok, heard, tokens


VOWELS = {"ɑ", "æ", "ə", "aʊ", "aɪ", "ɛ", "ɝ", "eɪ", "ɪ", "i", "oʊ", "ɔɪ", "ʊ", "u"}


def _check_window(probs, id2tok, start_s: float, end_s: float, expected: str, exclude: set, flap: bool = False) -> dict:
    reqs = FLAP_REQ if (flap and expected == "t") else EXPECTED.get(expected)
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
    is_flap = flap and expected == "t"
    if is_flap:
        # Only a clearly hard T counts as the error; anything else stays unsure.
        p_hard_t = max((float(seg[:, i].max()) for i, t in id2tok.items() if t == "t"), default=0.0)
        other_tok, other_p, any_other_p = "t", p_hard_t, p_hard_t
    if p_exp >= CONFIRM_P:
        verdict = "confirmed"
    elif p_exp < MISSING_P and (any_other_p >= OTHER_P or vowel_ok):
        verdict = "missing"
    else:
        verdict = "unsure"
    note = None
    if verdict == "missing" and is_flap:
        note = "In this word the t turns to a d."
    elif verdict == "missing" and failing is _R and len(reqs) > 1:
        note = "The r sound wasn't heard."
        vowel = max(((float(seg[:, i].max()), t) for i, t in id2tok.items() if t in reqs[0]), default=(0.0, None))
        other_tok = vowel[1] or other_tok
    elif verdict == "missing" and failing is _R:
        note = "The r sound wasn't heard."
    return {"expected": expected, "verdict": verdict, "p_expected": round(p_exp, 2),
            "heard": DISPLAY.get(other_tok, other_tok) if other_tok and verdict != "confirmed" else None,
            "p_heard": round(other_p, 2), "note": note, "flap": bool(flap and expected == "t")}


def listen(wav_bytes: bytes, windows: List[dict]) -> Optional[dict]:
    """windows: [{expected, start_s, end_s}] from Azure phoneme timings (16 kHz mono PCM wav)."""
    if not available():
        return None
    if _state["model"] is None:
        return _ask_worker(wav_bytes, windows)
    probs, id2tok, heard, tokens = _posteriors(wav_bytes)
    checks = []
    for i, w in enumerate(windows):
        neighbours = set()
        for j in (i - 1, i + 1):
            if 0 <= j < len(windows):
                neighbours |= set().union(*EXPECTED.get(windows[j]["expected"], []))
        # For a flap slot, a hard T is exactly the error we want to name, so don't exclude it.
        if w.get("flap"):
            neighbours.discard("t")
        checks.append(_check_window(probs, id2tok, w["start_s"], w["end_s"], w["expected"], neighbours, flap=w.get("flap", False)))
    nuclei = sum(1 for i, t in enumerate(tokens) if t in VOWELS and not (t == "ɝ" and i > 0 and tokens[i - 1] in VOWELS))
    return {"heard": heard, "checks": checks, "tokens": tokens, "heard_vowels": nuclei}
