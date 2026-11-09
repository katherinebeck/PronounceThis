"""Third ear for fricatives: band energies + voicing inside an Azure consonant window.

Sibilance (s z ʃ ʒ are loud with energy above 2 kHz; f v θ ð are quiet and diffuse) and voicing
(s/z, f/v, θ/ð, ʃ/ʒ differ only by the vocal folds). f↔θ is not attempted — the spectra are
too alike at 16 kHz. Only asserts when the measurement is clear-cut.
"""
import io
import math
import wave
from typing import Dict, Optional, Tuple

import numpy as np

SIBILANT = {"s", "z", "ʃ", "ʒ"}
NON_SIBILANT = {"f", "v", "θ", "ð"}
VOICED = {"z": "s", "v": "f", "ð": "θ", "ʒ": "ʃ"}
VOICELESS = {v: k for k, v in VOICED.items()}
CHECKED = SIBILANT | NON_SIBILANT

LEVEL_SIBILANT = 0.08      # fricative rms / word peak rms at or above → sibilant (Hannah s/z/ʃ 0.09–0.45, f/θ 0.036–0.046)
LEVEL_NON_SIBILANT = 0.03  # below → non-sibilant (deliberately strict: soft speakers must not be told their s is an f)
MIN_FRAMES = 4             # noise frames needed before anything is asserted
VOICING_ON = 0.60          # share of frames with a clear pitch → voiced (Hannah z 0.69–0.71, s 0.0)
VOICING_OFF = 0.15         # below → voiceless
CENTROID_NOISE = 1800.0    # spectral centroid (Hz) above which a frame is fricative noise, not vowel
NAMES = {"s": "s as in sip", "z": "z as in zoo", "ʃ": "sh as in ship", "ʒ": "zh as in measure", "f": "f as in fan",
         "v": "v as in van", "θ": "th as in think", "ð": "th as in then"}


def _load(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        sr = wf.getframerate()
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0, sr


def measure(wav_bytes: bytes, start_s: float, end_s: float) -> Optional[Dict[str, float]]:
    """{level, hf, voicing} over the noise-like frames of the window (Azure's consonant windows
    bleed into the neighbouring vowel, so frames are picked by spectral centroid, not loudness)."""
    audio, sr = _load(wav_bytes)
    a, b = int(max(0.0, start_s - 0.02) * sr), int((end_s + 0.02) * sr)
    seg = audio[a:b]
    win, hop = int(0.020 * sr), int(0.010 * sr)
    if len(seg) < win + hop:
        return None
    peak = 0.0
    for i in range(0, len(audio) - win + 1, hop):
        peak = max(peak, math.sqrt(float(np.mean(audio[i:i + win] ** 2))))
    peak = peak or 1e-9
    freqs = np.fft.rfftfreq(win, 1 / sr)
    hann = np.hanning(win)
    lo, hi = int(sr / 400), int(sr / 80)
    noise_frames = []
    for i in range(0, len(seg) - win + 1, hop):
        f = seg[i:i + win]
        rms = math.sqrt(float(np.mean(f ** 2)))
        if rms < 0.03 * peak:
            continue
        spec = np.abs(np.fft.rfft(f * hann)) ** 2
        centroid = float((spec * freqs).sum() / (spec.sum() or 1e-12))
        if centroid < CENTROID_NOISE:
            continue
        band = spec[(freqs >= 1000) & (freqs <= 8000)].sum() or 1e-12
        hf = float(spec[(freqs >= 2000) & (freqs <= 8000)].sum() / band)
        g = f - f.mean()
        ac = np.correlate(g, g, mode="full")[len(g) - 1:]
        voiced = ac[0] > 0 and float(ac[lo:hi].max() / ac[0]) > 0.45
        noise_frames.append((rms, hf, voiced))
    if len(noise_frames) < 2:
        return None
    return {"level": round(float(np.median([r for r, _, _ in noise_frames])) / peak, 3),
            "hf": round(float(np.median([h for _, h, _ in noise_frames])), 3),
            "voicing": round(sum(1 for _, _, v in noise_frames if v) / len(noise_frames), 2),
            "frames": len(noise_frames)}


def judge(expected: str, m: Dict[str, float], final: bool) -> Optional[dict]:
    """None when acceptable/unsure; else {"heard", "note"}."""
    if expected not in CHECKED:
        return None
    # Sibilance class.
    if m.get("frames", 0) < MIN_FRAMES:
        return None
    if expected in NON_SIBILANT and m["level"] >= LEVEL_SIBILANT:
        heard = "z" if (expected in VOICED and m["voicing"] >= VOICING_ON) else "s"
        return {"heard": heard, "note": f"This sounded like a hissing {NAMES[heard]} — Americans use the softer {NAMES[expected]} here."}
    if expected in SIBILANT and m["level"] < LEVEL_NON_SIBILANT:
        heard = "v" if (expected in VOICED and m["voicing"] >= VOICING_ON) else "f"
        return {"heard": heard, "note": f"The {NAMES[expected]} was too soft — it sounded like {NAMES[heard]}. Let the air hiss."}
    # Voicing, same class. Final voiced fricatives are naturally devoiced in American speech.
    if expected in VOICED and not final and m["voicing"] <= VOICING_OFF:
        other = VOICED[expected]
        return {"heard": other, "note": f"No voice was heard — it sounded like {NAMES[other]}. Keep the vocal folds buzzing through the {NAMES[expected]}."}
    if expected in VOICELESS and m["voicing"] >= VOICING_ON:
        other = VOICELESS[expected]
        return {"heard": other, "note": f"This was voiced — it sounded like {NAMES[other]}. The {NAMES[expected]} is just air, no buzz."}
    return None
