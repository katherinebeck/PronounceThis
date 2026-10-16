"""Ear worker: runs inside /opt/ear-venv (torch + transformers) as a child process.
Protocol: one JSON object per line on stdin → one JSON line on stdout.
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phoneme_ear  # noqa: E402

phoneme_ear._load()
sys.stdout.write(json.dumps({"ready": phoneme_ear.available(), **phoneme_ear.status()}) + "\n")
sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        out = phoneme_ear.listen(base64.b64decode(req["wav_b64"]), req["windows"]) or {}
    except Exception as exc:  # noqa: BLE001
        out = {"error": str(exc)[:300]}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
