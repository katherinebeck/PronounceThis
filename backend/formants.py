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
# Glide (diphthongisation) check on pure vowels.
GLIDE_CHECKED = {"i", "u", "ɪ", "ʊ", "ɛ", "æ", "ɑ", "ɔ"}
GLIDE_MIN_S = 0.11   # vowel must be this long to judge movement
GLIDE_F2 = 0.30      # F2 travel (log-Hz) start→end of the vowel body towards the target…
GLIDE_F1 = 0.20      # …together with F1 falling (the start was a more open/central vowel).
                     # Hannah's clean takes move up to 0.23/0.30 on one axis only.
MAX_MOVE = 0.45       # total log-Hz movement across the steadiest run; more = no steady vowel found
# Swaps we never flag: General American itself allows them.
ALLOWED = {("ɔ", "ɑ"), ("ʌ", "ə")}
ROUNDED_BACK = {"ɔ", "ʊ", "u"}   # an expected ɑ landing here = lips rounded = the British/Australian ɒ
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


def _frame_all(frame: np.ndarray, sr: int) -> list:
    a = _lpc(frame, 2 + sr // 1000)
    if a is None:
        return []
    cands = []
    for r in np.roots(a):
        if r.imag <= 0:
            continue
        f = math.atan2(r.imag, r.real) * sr / (2 * math.pi)
        bw = -0.5 * sr / math.pi * math.log(max(abs(r), 1e-9))
        if 150 <= f <= 4000 and bw < 450:
            cands.append(f)
    return sorted(cands)


def _frame_formants(frame: np.ndarray, sr: int) -> Optional[Tuple[float, float]]:
    cands = _frame_all(frame, sr)
    if len(cands) < 2 or cands[1] - cands[0] < 150:
        return None
    return cands[0], cands[1]


R_F3_BASE = 2250.0   # women: r-coloured vowels sit at F3 ≈ 1800–2100 Hz, plain vowels ≥ 2500 Hz
R_F3_MIN_FRAMES = 3


def f3_median(wav_bytes: bytes, start_s: float, end_s: float) -> Optional[float]:
    """Median F3 over the louder frames of the window: the acoustic signature of r-colouring is a low F3."""
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        sr = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    a, b = int(max(0.0, start_s) * sr), int(end_s * sr)
    seg = audio[a:b]
    win, hop = int(0.025 * sr), int(0.010 * sr)
    if len(seg) < win + 2 * hop:
        return None
    seg = np.append(seg[0], seg[1:] - 0.97 * seg[:-1])
    hamming = np.hamming(win)
    frames = [seg[i:i + win] for i in range(0, len(seg) - win + 1, hop)]
    rms = np.array([math.sqrt(float(np.mean(f ** 2))) for f in frames])
    f3s = []
    for f, r in zip(frames, rms):
        if r < 0.4 * rms.max():
            continue
        c = _frame_all(f * hamming, sr)
        if len(c) >= 3 and c[1] - c[0] >= 150 and c[2] - c[1] >= 200:
            f3s.append(c[2])
    if len(f3s) < R_F3_MIN_FRAMES:
        return None
    return float(np.median(f3s))


def rhotic_missing(f3: float, scale: Optional[Tuple[float, float]]) -> bool:
    """True when F3 is too high for an r-coloured vowel, for this speaker's size."""
    k = scale[1] if scale else 1.0
    return f3 >= R_F3_BASE * k


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


def trajectory(wav_bytes: bytes, start_s: float, end_s: float) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """(F1,F2) at the start and the end of the vowel body (middle 70 % of the window, so the
    consonant transitions at the edges don't count). None when the vowel is too short to tell."""
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        sr = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    dur = end_s - start_s
    if dur < GLIDE_MIN_S:
        return None
    a, b = int((start_s + dur * 0.15) * sr), int((end_s - dur * 0.15) * sr)
    seg = audio[max(0, a):min(len(audio), b)]
    win, hop = int(0.025 * sr), int(0.010 * sr)
    seg = np.append(seg[0], seg[1:] - 0.97 * seg[:-1])
    hamming = np.hamming(win)
    pts = [ff for ff in (_frame_formants(seg[i:i + win] * hamming, sr) for i in range(0, len(seg) - win + 1, hop)) if ff]
    if len(pts) < 6:
        return None
    third = max(2, len(pts) // 3)
    head, tail = np.array(pts[:third]), np.array(pts[-third:])
    return (float(np.median(head[:, 0])), float(np.median(head[:, 1]))), (float(np.median(tail[:, 0])), float(np.median(tail[:, 1])))


def judge_glide(expected: str, traj: Tuple[Tuple[float, float], Tuple[float, float]]) -> Optional[dict]:
    """A pure vowel that travels: Australian/British [əi] for i, [əʉ]/[ɪu] for u, etc."""
    if expected not in GLIDE_CHECKED:
        return None
    (f1a, f2a), (f1b, f2b) = traj
    d1, d2 = math.log(f1b / f1a), math.log(f2b / f2a)
    # Both axes must travel, in the direction of an onglide from a central vowel towards the target
    # (front vowels: F2 rising + F1 falling; back vowels: F2 falling + F1 falling).
    if expected in ("i", "ɪ", "ɛ", "æ") and not (d2 >= GLIDE_F2 and d1 <= -GLIDE_F1):
        return None
    if expected in ("u", "ʊ", "ɔ", "ɑ") and not (d2 <= -GLIDE_F2 and d1 <= -GLIDE_F1):
        return None
    start = "ə" if expected in ("i", "ɪ", "u", "ʊ") else "another vowel"
    return {"badge": "glided", "heard": f"{start}{expected}",
            "note": f"The {expected} moved while you said it — it started on {start if start != 'ə' else 'a schwa (ə)'} and slid into {expected}. Americans hold one pure {expected} from start to finish."}



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


FRONTED_U_F2 = 1.52   # u with F2 this far above the speaker's target is a fronted ʉ (Aussie/British "oo"); clean American u reaches 1.42×
OWN_U_RATIO = 1.22    # …or this far above the speaker's own clean u (coach's clean food/who sat 1206–1351 Hz, Aussie ʉ ≥ 1650)
OWN_U_MIN = 2         # own-u takes needed before that anchor is used
FRONTED_U_F2_CORONAL, OWN_U_RATIO_CORONAL = 1.80, 1.40   # after a coronal (Hannah's zoo u: F2 1487)
CORONALS = {"t", "d", "s", "z", "n", "l", "ʃ", "ʒ", "tʃ", "dʒ", "θ", "ð", "j"}
FRONTED_U_TIP = ("Tongue: the arch of the back of the tongue is high — don't let it pull back into the throat; "
                 "the tip rests at the lower gum ridge. Lips: stretched forward in a small round circle. Lower jaw: only slightly open.")
STRICT_RATIO = 2.2    # next to a nasal/liquid the vowel is coloured — demand a much clearer miss


def own_u_f2(profile: Optional[dict]) -> Optional[float]:
    """Median F2 of this speaker's own confirmed u takes (needs OWN_U_MIN of them)."""
    e = (profile or {}).get("u") or {}
    return float(np.median(e["f2"])) if len(e.get("f2") or []) >= OWN_U_MIN else None


FRONTED_O_NOTE = ("The o was made too far forward — the Australian/British əʉ. Americans start on a pure back o "
                  "with the lips rounded and glide to ʊ.")
O_START = (555, 1100)   # where a General American oʊ begins (women); the Australian əʉ begins central, F2 ≈ 1500+
O_START_F2 = 1.35


FLAT_MOVE = 0.18   # a diphthong whose F1/F2 travel less than this (log-Hz) never glided (Hannah's clean ones move 0.29–0.91)
FLAT = {"aʊ": ("ɑ", "ʊ", "raise the back of the tongue and round the lips"), "aɪ": ("ɑ", "ɪ", "arch the tongue up and forward"),
        "eɪ": ("ɛ", "ɪ", "close the jaw and arch the tongue higher"), "ɔɪ": ("ɔ", "ɪ", "move the tongue arch forward and spread the lips")}


def judge_flat(expected: str, traj: Tuple[Tuple[float, float], Tuple[float, float]]) -> Optional[dict]:
    """A diphthong said as one steady vowel (now → "nah", ride → "rahd")."""
    if expected not in FLAT:
        return None
    (f1a, f2a), (f1b, f2b) = traj
    if math.hypot(math.log(f1b / f1a), math.log(f2b / f2a)) >= FLAT_MOVE:
        return None
    first, second, how = FLAT[expected]
    return {"heard": first, "badge": "no glide",
            "note": f"The {expected} stayed on one vowel — it sounded like a long {first} and never moved. "
                    f"Start on {first}, then {how} to finish on {second}."}


def judge_ou(traj: Tuple[Tuple[float, float], Tuple[float, float]], scale: Optional[Tuple[float, float]] = None,
             own_u: Optional[float] = None) -> Optional[dict]:
    """oʊ said as the fronted Australian/British [əʉ]: starts central and/or ends on a fronted ʉ."""
    (f1a, f2a), (f1b, f2b) = traj
    scales = [scale] if scale else [(s, s) for s in SCALES]
    floor = OWN_U_RATIO * own_u if own_u else 0.0
    high_end = all(f1b <= 1.6 * TARGETS["u"][0] * k[0] for k in scales)   # the tail is a close vowel, not an open ɑ
    central_start = all(f2a >= O_START_F2 * O_START[1] * k[1] for k in scales)
    fronted_end = all(f2b >= max(floor, FRONTED_U_F2 * TARGETS["u"][1] * k[1]) for k in scales)
    if high_end and (central_start or fronted_end):
        return {"heard": "əʉ", "badge": "too far forward", "tip": None, "note": FRONTED_O_NOTE}
    return None


def judge(expected: str, point: Tuple[float, float], scale: Optional[Tuple[float, float]] = None, strict: bool = False,
          own_u: Optional[float] = None, after_coronal: bool = False) -> Optional[dict]:
    """None when the vowel is acceptable/unsure; else {"heard": other vowel, "note": coaching line}.
    With a speaker scale the table is fitted to this speaker; without one every plausible size must agree."""
    if expected not in CHECKED:
        return None
    scales = [scale] if scale else [(s, s) for s in SCALES]
    if expected == "u":
        # Fronted ʉ keeps F1 low (so it still looks like u) but pushes F2 up towards the front vowels.
        # Once the speaker's own clean u is known it anchors the line: real American u varies ±10% take to take.
        # After t d s z n l (zoo, too, new) General American itself fronts u, so the line moves up.
        mult, own_mult = (FRONTED_U_F2_CORONAL, OWN_U_RATIO_CORONAL) if after_coronal else (FRONTED_U_F2, OWN_U_RATIO)
        floor = own_mult * own_u if own_u else 0.0
        if all(point[1] >= max(floor, mult * TARGETS["u"][1] * k[1]) and point[0] <= 1.6 * TARGETS["u"][0] * k[0] for k in scales):
            return {"heard": None, "badge": "too far forward", "tip": FRONTED_U_TIP, "note": None}
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
    if expected == "ɑ" and other in ROUNDED_BACK:
        return {"heard": "ɒ", "note": "The vowel was rounded and closed — the British/Australian short o (ɒ). "
                                      "Americans use the open ɑ here: unround the lips and let the jaw drop."}
    if expected == "ɔ" and other in ("u", "ʊ"):
        return {"heard": "oː", "note": "The vowel was too closed — the tight British ɔː (as in RP water). "
                                       "The American ɔ is more open: drop the jaw and keep the rounding loose."}
    note = f"The vowel sounded closer to {NAMES.get(other, other)} — Americans use {NAMES.get(expected, expected)} here."
    return {"heard": other, "note": note}
