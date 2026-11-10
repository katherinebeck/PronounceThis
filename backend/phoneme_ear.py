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
import wave
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
    "ɪɹ": [{"ɪ", "i"}, _R], "ʊɹ": [{"ʊ", "u", "ɑ"}, _R], "aɪɹ": [{"aɪ", "ɑ"}, _R], "aʊɹ": [{"aʊ", "ɑ"}, _R],
    "ɝ": [_R], "ɚ": [_R], "ɹ": [_R], "r": [_R],
    "ɑ": [{"ɑ"}], "ɔ": [{"ɑ", "ə"}], "ʌ": [{"ə"}], "ə": [{"ə", "ɪ"}],
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
# Production: the ear runs as its own small service (ear-service/); the backend only talks HTTP to it.
EAR_URL = os.environ.get("EAR_URL", "").rstrip("/")
EAR_SECRET = os.environ.get("EAR_SECRET", "")
REMOTE_TIMEOUT_S = 25
REMOTE_CONNECT_S = 10   # a suspended Fly machine resumes in ~1–2 s; a stopped one needs ~30 s (model load) and will miss this take
REMOTE_RECHECK_S = 60


def status() -> dict:
    mode = "remote" if EAR_URL else ("worker" if _worker["proc"] is not None else "in-process")
    return {"model": MODEL_ID, "status": _state["status"], "error": _state["error"], "mode": mode}


def available() -> bool:
    if EAR_URL:
        return _state["status"] == "ready"
    return _state["model"] is not None or (_worker["proc"] is not None and _state["status"] == "ready")


def _check_remote() -> bool:
    import httpx
    try:
        r = httpx.get(f"{EAR_URL}/health", headers={"X-Ear-Secret": EAR_SECRET}, timeout=8)
        body = r.json() if r.status_code == 200 else {}
        if body.get("ready"):
            if _state["status"] != "ready":
                logger.info("phoneme ear ready via %s (%s)", EAR_URL, body.get("model"))
            _state.update(status="ready", error=None)
            return True
        _state.update(status="error", error=f"ear service {r.status_code}: {str(body.get('error') or body.get('status') or r.text)[:200]}")
    except Exception as exc:  # noqa: BLE001
        _state.update(status="error", error=f"ear service unreachable: {str(exc)[:200]}")
    return False


def _remote_monitor() -> None:
    """Re-check the ear only while it is down: a steady 60 s heartbeat would keep an auto-suspending
    Fly machine awake around the clock. Once ready, the next real take is the check."""
    import time
    while True:
        if _state["status"] != "ready":
            _check_remote()
        time.sleep(REMOTE_RECHECK_S)


def _ask_remote(wav_bytes: bytes, windows: List[dict]) -> Optional[dict]:
    import httpx
    try:
        r = httpx.post(f"{EAR_URL}/listen", json={"wav_b64": base64.b64encode(wav_bytes).decode(), "windows": windows},
                       headers={"X-Ear-Secret": EAR_SECRET}, timeout=httpx.Timeout(REMOTE_TIMEOUT_S, connect=REMOTE_CONNECT_S))
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        out = r.json()
        if out.get("error"):
            raise RuntimeError(out["error"])
        _state["error"] = None
        return out or None
    except httpx.ConnectError as exc:
        logger.warning("phoneme ear service unreachable, Azure-only for this take: %s", exc)
        _state.update(status="error", error=f"ear service unreachable: {str(exc)[:200]}")  # monitor starts re-checking
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("phoneme ear service failed, Azure-only for this take: %s", exc)
        _state["error"] = str(exc)[:300]  # a busy/slow take is not an outage: stay ready for the next one
        return None


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
    if EAR_URL:
        _state["status"] = "loading"
        threading.Thread(target=_remote_monitor, name="phoneme-ear-remote", daemon=True).start()
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
GLIDES = {"j", "w"}
# Short sounds that, heard right before a vowel, are an onglide (Aussie/British "yoo", "ə-oo", "ə-oh")
# rather than a syllable of their own. Before u, i/ɪ count too ("ee-oo" = yoo).
ONGLIDE_TOKENS = {"j", "w", "ə", "ɪ", "ʊ"}
# Before u ("yoo", "ə-oo") and oʊ (Aussie/British "ə-oh") any inserted vowel is an onglide, never a syllable.
ONGLIDE_ANY_HOSTS = {"u", "oʊ"}
# Acoustically confusable pairs the ear never asserts as "missing" on its own (Azure still scores them).
NEAR = {"ð": {"θ", "d", "v"}, "θ": {"ð", "f"}, "s": {"z"}, "z": {"s"}, "f": {"v", "θ", "s"}, "v": {"f", "ð", "z"},
        "ʃ": {"ʒ"}, "ʒ": {"ʃ"}, "w": {"m", "v"}, "ʌ": {"ɑ"}, "ɑ": {"ə"}, "ɔ": {"oʊ"}}
SURE_NEAR = {("θ", "f")}   # the one near pair the ear may call alone, and only when certain
SURE_NEAR_P, SURE_NEAR_EXP_P = 0.95, 0.03

R_COMBOS = {"ɑɹ", "ɔɹ", "ɛɹ", "ɪɹ", "ʊɹ", "aɪɹ", "aʊɹ"}
EXPECTED_VOWELS = set(EXPECTED) & (VOWELS | {"ɔ", "ʌ", "ɚ"} | R_COMBOS)


REDUCED_I = [{"ɪ", "ə"}]  # unstressed ɪ (be-lieve, mu-sic) is said as ə by most Americans


def _reqs_for(w: dict) -> list:
    if w.get("flap") and w["expected"] == "t":
        return FLAP_REQ
    if w.get("reduced") and w["expected"] == "ɪ":
        return REDUCED_I
    return EXPECTED.get(w["expected"], [])


def _is_vowel_req(req: set) -> bool:
    return req is not _R and bool(req & VOWELS)


def _align(flat: List[set], tokens: List[str]) -> List[tuple]:
    """Needleman-Wunsch of heard tokens against the expected requirement sets.
    Returns ops: ('match'|'sub', req_idx, tok) · ('del', req_idx, None) · ('ins', req_idx_before, tok)."""
    n, m = len(flat), len(tokens)
    gap = -1.0
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0], back[i][0] = i * gap, "del"
    for j in range(1, m + 1):
        score[0][j], back[0][j] = j * gap, "ins"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            tok = tokens[j - 1]
            if tok in flat[i - 1]:
                sub = 2.0
            elif flat[i - 1] is _R and tok in VOWELS:
                sub = -0.5   # a plain vowel where an r-coloured vowel should be (British "bird")
            elif (tok in VOWELS) == _is_vowel_req(flat[i - 1]):
                sub = 0.0   # same class (vowel for vowel): a substitution, not a gap
            else:
                sub = -1.5
            diag = score[i - 1][j - 1] + sub
            up, left = score[i - 1][j] + gap, score[i][j - 1] + gap
            best = max(diag, up, left)
            score[i][j] = best
            # Ties: push insertions late (trailing artefacts) rather than splitting a diphthong.
            back[i][j] = "ins" if best == left else ("diag" if best == diag else "del")
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        b = back[i][j]
        if b == "diag":
            ops.append(("match" if tokens[j - 1] in flat[i - 1] else "sub", i - 1, tokens[j - 1]))
            i, j = i - 1, j - 1
        elif b == "del":
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", i, tokens[j - 1]))
            j -= 1
    ops.reverse()
    return ops


def _sequence_view(windows: List[dict], tokens: List[str]) -> dict:
    """Order-based second opinion: which expected sounds the heard sequence contains, what was
    substituted, and where extra vowel/glide sounds were inserted (onglide vs. extra syllable)."""
    flat, owner = [], []  # requirement sets in order, and the window index each belongs to
    for i, w in enumerate(windows):
        reqs = _reqs_for(w)
        for r in reqs:
            flat.append(r)
            owner.append(i)
    present = [True] * len(windows)      # every requirement of the slot matched in sequence
    heard = [None] * len(windows)        # substituted token when the slot didn't match
    intrusion = [None] * len(windows)    # {"tok", "where"} extra sound glued to this vowel
    r_dropped = [False] * len(windows)   # r-coloured slot: vowel said, R requirement absent
    extra_nuclei = 0
    if not flat or not tokens:
        return {"present": present, "heard": heard, "intrusion": intrusion, "extra_nuclei": 0, "r_dropped": r_dropped}
    # CTC emits the same vowel twice when it is long or glided ("liiv"); that is one sound.
    tokens = [t for i, t in enumerate(tokens) if i == 0 or t != tokens[i - 1]]
    ops = _align(flat, tokens)
    matched_req = [False] * len(flat)
    aligned_req = [False] * len(flat)   # matched or substituted (something was said in that slot)
    for op, k, tok in ops:
        if op == "match":
            matched_req[k] = aligned_req[k] = True
        elif op == "sub":
            aligned_req[k] = True
            heard[owner[k]] = heard[owner[k]] or tok
    for k, ok in enumerate(matched_req):
        if not ok:
            present[owner[k]] = False
    for i, w in enumerate(windows):
        ks = [k for k, o in enumerate(owner) if o == i]
        if len(ks) == 2 and flat[ks[1]] is _R and aligned_req[ks[0]] and not matched_req[ks[1]]:
            r_dropped[i] = True
        # ɝ/ɚ said as a plain vowel (British "bird" = bɜːd): the R slot was filled by a vowel.
        if len(ks) == 1 and flat[ks[0]] is _R and not matched_req[ks[0]] and heard[i] in VOWELS:
            r_dropped[i] = True
    last_aligned = max((k for k, ok in enumerate(aligned_req) if ok), default=-1)
    # Group consecutive insertions by the requirement they sit in front of.
    groups: dict = {}
    for op, k, tok in ops:
        if op == "ins":
            groups.setdefault(k, []).append(tok)
    for k, toks in groups.items():
        vowelish = [t for t in toks if t in VOWELS or t in GLIDES]
        if not vowelish or k > last_aligned:
            continue  # consonant noise, or trailing artefacts after the word ended
        nxt = windows[owner[k]] if k < len(flat) else None
        prv = windows[owner[k - 1]] if k > 0 else None
        if nxt is not None and prv is nxt and all(t in ONGLIDE_TOKENS for t in vowelish):
            continue  # a glide inside an r-combo (hour → [aʊwɚ], fire → [aɪjɚ]) is just the transition into the r
        nxt_vowel = nxt is not None and nxt["expected"] in EXPECTED_VOWELS and aligned_req[k]
        prv_vowel = prv is not None and prv["expected"] in EXPECTED_VOWELS and aligned_req[k - 1]
        if nxt_vowel:
            # A stressed vowel approached through another vowel is a diphthongised vowel (Aussie [əi] for i),
            # never an extra syllable; only an unstressed host (alu-min-i-um) can gain a syllable.
            stressed = nxt.get("stress") in (1, 2) or nxt["expected"] in ONGLIDE_ANY_HOSTS
            allowed = (VOWELS | GLIDES) if stressed else ONGLIDE_TOKENS
            if all(t in allowed for t in vowelish):
                intrusion[owner[k]] = intrusion[owner[k]] or {"tok": vowelish[0], "where": "before"}
            else:
                extra_nuclei += 1  # a full vowel in front of a vowel: another syllable (alu-min-i-um)
        elif prv_vowel and all(t in ONGLIDE_TOKENS or (t == "u" and prv["expected"] in ONGLIDE_ANY_HOSTS) for t in vowelish):
            continue  # offglide (æ→[æə] before nasals is normal American; oʊ→[oʊu] is a fronted tail the formant ear judges)
        elif any(t in VOWELS for t in vowelish):
            extra_nuclei += 1
    return {"present": present, "heard": heard, "intrusion": intrusion, "extra_nuclei": extra_nuclei, "r_dropped": r_dropped}


def _check_window(probs, id2tok, start_s: float, end_s: float, expected: str, exclude: set, flap: bool = False, reduced: bool = False) -> dict:
    reqs = _reqs_for({"expected": expected, "flap": flap, "reduced": reduced})
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
    r_weak = _R in reqs and req_p[reqs.index(_R)] < MISSING_P
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
    # Sounds the model habitually confuses (ð/θ, s/z…) are never asserted as missing by the ear alone…
    # …except θ→f when the model is certain (fink: f 0.97, θ 0.02); its clean-θ readings run ≥ 0.9.
    sure = (expected, other_tok) in SURE_NEAR and other_p >= SURE_NEAR_P and p_exp <= SURE_NEAR_EXP_P
    if verdict == "missing" and not is_flap and other_tok in NEAR.get(expected, ()) and not sure:
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
            "p_heard": round(other_p, 2), "note": note, "flap": bool(flap and expected == "t"), "r_failed": failing is _R or r_weak}


PURE_HOSTS = {"i", "u", "ɪ", "ʊ"}
GLIDE_SUBS = {("i", "eɪ"): "əi", ("i", "ɛ"): "əi", ("u", "oʊ"): "əu", ("u", "aʊ"): "əu", ("ɪ", "eɪ"): "əɪ"}


def _glide_note(expected: str, glide: str) -> str:
    return (f"The {expected} moved while you said it — it started on a schwa (ə) and slid into {expected} ({glide}). "
            f"Americans hold one pure {expected} from start to finish.")


def _intrusion_note(expected: str, intr: dict) -> str:
    tok = DISPLAY.get(intr["tok"], intr["tok"])
    shown = expected[:-1] if expected in R_COMBOS else expected
    name = " (a schwa)" if intr["tok"] == "ə" else (" (a y sound)" if intr["tok"] == "j" else "")
    if intr["where"] == "before":
        return f"We heard an extra sound before the {shown} — it sounded like {tok}{shown}{name}. Remove it and go straight into the pure {shown} sound."
    return f"We heard an extra sound after the {shown} — it sounded like {shown}{tok}{name}. Finish the {shown} cleanly without adding a vowel."


CROP_MARGIN_S = 0.25   # audio kept either side of the Azure word span


def _crop(wav_bytes: bytes, windows: List[dict]):
    """Send the model only the word (plus a margin): inference time grows with audio length, and a
    mic take carries a second or two of room either side (3.5 s → ~20 s on a shared CPU)."""
    timed = [w for w in windows if w.get("end_s", 0) > w.get("start_s", 0)]
    if not timed:
        return wav_bytes, windows
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        sr, n = wf.getframerate(), wf.getnframes()
        params = wf.getparams()
        frames = wf.readframes(n)
    a = max(0.0, min(w["start_s"] for w in timed) - CROP_MARGIN_S)
    b = min(n / sr, max(w["end_s"] for w in timed) + CROP_MARGIN_S)
    if a < 0.05 and b > n / sr - 0.05:
        return wav_bytes, windows
    width = params.sampwidth * params.nchannels
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(frames[int(a * sr) * width:int(b * sr) * width])
    shifted = [{**w, "start_s": max(0.0, w["start_s"] - a), "end_s": max(0.0, w["end_s"] - a)} for w in windows]
    return out.getvalue(), shifted


def listen(wav_bytes: bytes, windows: List[dict]) -> Optional[dict]:
    """windows: [{expected, start_s, end_s}] from Azure phoneme timings (16 kHz mono PCM wav)."""
    if not available():
        return None
    wav_bytes, windows = _crop(wav_bytes, windows)
    if EAR_URL:
        return _ask_remote(wav_bytes, windows)
    if _state["model"] is None:
        return _ask_worker(wav_bytes, windows)
    probs, id2tok, heard, tokens = _posteriors(wav_bytes)
    checks = []
    for i, w in enumerate(windows):
        neighbours = set()
        for j in (i - 1, i + 1):
            if 0 <= j < len(windows):
                reqs = _reqs_for(windows[j])
                neighbours |= set().union(*reqs)
        checks.append(_check_window(probs, id2tok, w["start_s"], w["end_s"], w["expected"], neighbours, flap=w.get("flap", False), reduced=w.get("reduced", False)))
    seq = _sequence_view(windows, tokens)
    last = len(windows) - 1
    for i, c in enumerate(checks):
        # The window said "missing" but the sound is there in sequence (Azure mis-timed the slot).
        if c["verdict"] == "missing" and seq["present"][i] and not c.get("r_failed"):
            c["verdict"] = "unsure"
            c["heard"], c["note"] = None, None
        # A word-final p/t/k is often unreleased (normal American) — the ear can't judge it.
        if c["verdict"] == "missing" and i == last and c["expected"] in ("p", "t", "k") and not c.get("flap"):
            c["verdict"] = "unsure"
            c["heard"], c["note"] = None, None
        # R-coloured vowel: vowel said, no R anywhere in the sequence and none in the window → dropped R.
        if c["verdict"] == "unsure" and c.get("r_failed") and seq["r_dropped"][i] and (c.get("p_expected") or 0) < MISSING_P:
            c["verdict"], c["note"] = "missing", "The r sound wasn't heard."
            c["heard"] = DISPLAY.get(seq["heard"][i], seq["heard"][i]) if seq["heard"][i] else c["expected"][:-1]
        if c["verdict"] == "missing" and seq["heard"][i] and not c.get("r_failed") and not c.get("flap"):
            c["heard"] = DISPLAY.get(seq["heard"][i], seq["heard"][i])
        intr = seq["intrusion"][i]
        if intr and c["verdict"] != "missing":
            c["verdict"], c["intrusion"] = "missing", True
            if c["expected"] in PURE_HOSTS and intr["tok"] in VOWELS and intr["where"] == "before":
                c["heard"], c["glided"] = "ə" + c["expected"], True   # a vowel run-up = diphthongised vowel
                c["note"] = _glide_note(c["expected"], c["heard"])
            else:
                c["heard"] = DISPLAY.get(intr["tok"], intr["tok"])
                c["note"] = _intrusion_note(c["expected"], intr)
        # The model hears a diphthongised pure vowel as the nearest diphthong (Aussie [əi] → eɪ): name it as the glide.
        if c["verdict"] == "missing" and not c.get("intrusion") and (c["expected"], c.get("heard")) in GLIDE_SUBS:
            c["heard"], c["glided"] = GLIDE_SUBS[(c["expected"], c["heard"])], True
            c["note"] = _glide_note(c["expected"], c["heard"])
        c.pop("r_failed", None)
    return {"heard": heard, "checks": checks, "tokens": tokens, "extra_nuclei": seq["extra_nuclei"]}
