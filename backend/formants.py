"""Second ear for vowels: LPC formants (F1/F2) measured inside an Azure vowel window and
compared with General American targets (Peterson & Barney 1952, women; distances in log-Hz so
a speaker-size shift moves every target equally).

Only asserts when the vowel is clearly nearer another category whatever the speaker's size.
"""
import io
import math
import wave
from typing import Dict, List, Optional, Tuple

import numpy as np

# F1, F2 (Hz) — P&B women. Monophthongs only.
TARGETS: Dict[str, Tuple[float, float]] = {
    "i": (310, 2790), "ɪ": (430, 2480), "ɛ": (610, 2330), "æ": (860, 2050), "ɑ": (850, 1220),
    "ɔ": (590, 920), "ʊ": (470, 1160), "u": (370, 950), "ʌ": (760, 1400),
}
CHECKED = {"i", "ɪ", "ɛ", "æ", "ɑ", "ɔ", "ʊ", "u", "ʌ"}
# Shifts that cover children → large men relative to the women's table.
SCALES = (0.78, 0.88, 1.0, 1.12, 1.25)
CLEAR_RATIO = 1.6     # expected must be this many times further away than the nearest other vowel
MIN_FRAMES = 3
MAX_MOVE = 0.45       # total log-Hz movement across the steadiest run; more = no steady vowel found
# Swaps we never flag: General American itself allows them.
ALLOWED = {("ɔ", "ɑ"), ("ʌ", "ə")}
NAMES = {"ɑ": "the open ɑ as in father", "ɔ": "the rounded ɔ as in call", "ʌ": "ʌ as in cup", "æ": "æ as in cat",
         "ɛ": "ɛ as in bed", "ɪ": "ɪ as in ship", "i": "i as in sheep", "ʊ": "ʊ as in book", "u": "u as in food"}


def _lpc(frame: np.ndarray, order: int) -> Optional[np.ndarray]:
    r = np.correlate(frame, frame, mode="full")[len(frame) - 1: len(frame) + order]
    if r[0] <= 0:
        return None
    a = np.zeros(order + 1)
    a[0], e = 1.0, r[0]
    for i in range(1, order + 1):
        acc = r[i] + np.dot(a[1:i], r[i - 1:0:-1])
        k = -acc / e
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        e *= 1 - k * k
        if e <= 0:
            return None
    return a


def _frame_formants(frame: np.ndarray, sr: int) -> Optional[Tuple[float, float]]:
    a = _lpc(frame, 2 + sr // 1000)
    if a is None:
        return None
    roots = [r for r in np.roots(a) if r.imag > 0]
    cands = []
    for r in roots:
        f = math.atan2(r.imag, r.real) * sr / (2 * math.pi)
        bw = -0.5 * sr / math.pi * math.log(max(abs(r), 1e-9))
        if 150 <= f <= 4000 and bw < 450:
            cands.append(f)
    cands.sort()
    if len(cands) < 2 or cands[1] - cands[0] < 150:
        return None
    return cands[0], cands[1]


def measure(wav_bytes: bytes, start_s: float, end_s: float) -> Optional[Tuple[float, float]]:
    """F1/F2 at the steadiest 40 ms of the vowel (least formant movement) inside the window,
    so transitions into neighbouring consonants don't colour the reading. 16 kHz mono PCM wav."""
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        sr = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    a, b = int(max(0.0, start_s - 0.02) * sr), int((end_s + 0.02) * sr)
    seg = audio[max(0, a):min(len(audio), b)]
    win, hop = int(0.025 * sr), int(0.010 * sr)
    if len(seg) < win + 3 * hop:
        return None
    seg = np.append(seg[0], seg[1:] - 0.97 * seg[:-1])
    hamming = np.hamming(win)
    frames = []
    for i in range(0, len(seg) - win + 1, hop):
        fr = seg[i:i + win]
        frames.append((math.sqrt(float(np.mean(fr ** 2))), _frame_formants(fr * hamming, sr)))
    peak = max(r for r, _ in frames) or 1e-9
    pts: List[Optional[Tuple[float, float]]] = [ff if r >= 0.3 * peak else None for r, ff in frames]
    best, best_move = None, None
    for i in range(len(pts) - MIN_FRAMES):
        run = pts[i:i + MIN_FRAMES + 1]
        if any(p is None for p in run):
            continue
        move = sum(abs(math.log(run[k + 1][0]) - math.log(run[k][0])) + abs(math.log(run[k + 1][1]) - math.log(run[k][1]))
                   for k in range(len(run) - 1))
        if best_move is None or move < best_move:
            best, best_move = run, move
    if best is None or best_move > MAX_MOVE:
        return None
    arr = np.array(best)
    return float(np.median(arr[:, 0])), float(np.median(arr[:, 1]))


def _dist(p: Tuple[float, float], t: Tuple[float, float], k: Tuple[float, float]) -> float:
    return math.hypot(math.log(p[0]) - math.log(t[0] * k[0]), math.log(p[1]) - math.log(t[1] * k[1]))


PROFILE_MIN_VOWELS = 3   # distinct vowel categories needed before the speaker scale is trusted
PROFILE_KEEP = 12        # samples kept per vowel


def profile_add(profile: dict, vowel: str, point: Tuple[float, float]) -> dict:
    """Running per-speaker record of F1/F2 for vowels the recogniser confirmed (numbers only, no audio)."""
    entry = profile.setdefault(vowel, {"f1": [], "f2": []})
    entry["f1"] = (entry["f1"] + [round(point[0])])[-PROFILE_KEEP:]
    entry["f2"] = (entry["f2"] + [round(point[1])])[-PROFILE_KEEP:]
    return profile


def speaker_scale(profile: Optional[dict]) -> Optional[Tuple[float, float]]:
    """How this speaker's F1 and F2 sit relative to the women's table (geometric mean over vowels)."""
    if not profile:
        return None
    r1, r2 = [], []
    for v, e in profile.items():
        if v in TARGETS and e.get("f1") and e.get("f2"):
            r1.append(math.log(float(np.median(e["f1"])) / TARGETS[v][0]))
            r2.append(math.log(float(np.median(e["f2"])) / TARGETS[v][1]))
    if len(r1) < PROFILE_MIN_VOWELS:
        return None
    return math.exp(float(np.median(r1))), math.exp(float(np.median(r2)))


FRONTED_U_F2 = 1.40   # u with F2 this far above the speaker's target is a fronted ʉ (Aussie/British "oo")
FRONTED_U_TIP = ("Tongue: the arch of the back of the tongue is high — don't let it pull back into the throat; "
                 "the tip rests at the lower gum ridge. Lips: stretched forward in a small round circle. Lower jaw: only slightly open.")
STRICT_RATIO = 2.2    # next to a nasal/liquid the vowel is coloured — demand a much clearer miss


def judge(expected: str, point: Tuple[float, float], scale: Optional[Tuple[float, float]] = None, strict: bool = False) -> Optional[dict]:
    """None when the vowel is acceptable/unsure; else {"heard": other vowel, "note": coaching line}.
    With a speaker scale the table is fitted to this speaker; without one every plausible size must agree."""
    if expected not in CHECKED:
        return None
    scales = [scale] if scale else [(s, s) for s in SCALES]
    if expected == "u":
        # Fronted ʉ keeps F1 low (so it still looks like u) but pushes F2 up towards the front vowels.
        if all(point[1] >= FRONTED_U_F2 * TARGETS["u"][1] * k[1] and point[0] <= 1.6 * TARGETS["u"][0] * k[0] for k in scales):
            return {"heard": "ʉ", "badge": "too far forward", "tip": FRONTED_U_TIP, "note": None}
    ratio = STRICT_RATIO if strict else CLEAR_RATIO
    nearest_each = set()
    for k in scales:
        d = {v: _dist(point, t, k) for v, t in TARGETS.items()}
        best = min(d, key=d.get)
        if best == expected or d[expected] < ratio * d[best]:
            return None
        nearest_each.add(best)
    if len(nearest_each) != 1:
        return None
    other = nearest_each.pop()
    if (expected, other) in ALLOWED:
        return None
    note = f"The vowel sounded closer to {NAMES.get(other, other)} — Americans use {NAMES.get(expected, expected)} here."
    return {"heard": other, "note": note}
