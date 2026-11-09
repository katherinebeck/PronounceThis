"""Dump raw ear frames for clips: token runs (argmax) with frame spans and posterior-mass durations.

Run: cd /app/backend && /opt/ear-venv/bin/python tests/dump_ear_frames.py hannah_home charlie_aluminum
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import phoneme_ear as ear  # noqa: E402

ear._load()
for name in sys.argv[1:]:
    wav = f"/tmp/pt_rhotic/{name}.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", f"/tmp/pt_rhotic/{name}.mp3", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav], check=True)
    probs, id2tok, heard, tokens = ear._posteriors(open(wav, "rb").read())
    ids = probs.argmax(axis=-1)
    runs, prev, start = [], None, 0
    for i, t in enumerate(ids.tolist() + [-1]):
        if t != prev:
            if prev is not None and id2tok.get(prev) not in ear._IGNORE and prev != -1:
                runs.append((id2tok[prev], start, i))
            prev, start = t, i
    print(f"\n{name}: heard='{heard}' frames={len(probs)} ({len(probs) * ear.FRAME_S:.2f}s)")
    for tok, a, b in runs:
        idx = [i for i, t in id2tok.items() if t == tok][0]
        mass = float((probs[:, idx] > 0.3).sum()) * ear.FRAME_S
        print(f"  {tok:>4} frames {a:3d}-{b:3d} ({(a) * ear.FRAME_S:.2f}-{b * ear.FRAME_S:.2f}s) argmax={b - a} p>0.3 dur={mass:.2f}s")
