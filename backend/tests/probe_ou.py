"""Probe the oʊ fronting check: trajectory start/end F2 on bank clips.
Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/probe_ou.py"""
import io
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import _issue_jwt  # noqa: E402
import formants  # noqa: E402

CASES = [("boat", "tanya_boat"), ("boat", "hannah_boat"), ("boat", "hannah_bought"), ("home", "tanya_home"), ("home", "hannah_home"),
         ("go", "tanya_go"), ("go", "hannah_go"), ("no", "tanya_no"), ("no", "hannah_no")]
CACHE = "/tmp/pt_bank/_windows.json"


def wav(path):
    import subprocess
    out = path.replace(".mp3", ".wav")
    if not os.path.exists(out):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out], check=True)
    return open(out, "rb").read()


def main():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    ck = {"accent_session": _issue_jwt(os.environ["ADMIN_EMAILS"].split(",")[0].strip())}
    for word, f in CASES:
        p = f"/tmp/pt_bank/{f}.mp3"
        if not os.path.exists(p):
            continue
        key = f"{word}|{f}"
        if key not in cache:
            r = httpx.post("http://localhost:8001/api/practice/assess", data={"word": word}, files={"audio": (f, io.BytesIO(open(p, "rb").read()), "audio/mpeg")},
                           cookies=ck, headers={"X-Practice-Bank": "1"}, timeout=120).json()
            cache[key] = [{"expected": q["expected"], "start_s": q["start_s"], "end_s": q["end_s"], "ear": q.get("ear")} for q in r["phonemes"]]
            json.dump(cache, open(CACHE, "w"))
        w = wav(p)
        for ph in cache[key]:
            if ph["expected"] == "oʊ" and ph["start_s"] is not None:
                t = formants.trajectory(w, ph["start_s"], ph["end_s"])
                m = formants.measure(w, ph["start_s"], ph["end_s"])
                j = formants.judge_ou(t) if t else None
                print(f"{f:>14} dur={ph['end_s'] - ph['start_s']:.2f} ear={ph.get('ear')} mid={m and tuple(int(x) for x in m)} "
                      f"start={t and tuple(int(x) for x in t[0])} end={t and tuple(int(x) for x in t[1])} -> {j and j['heard']}")


main()
