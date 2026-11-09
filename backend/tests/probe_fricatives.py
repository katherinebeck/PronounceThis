"""Probe the fricative ear on bank clips. Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/probe_fricatives.py"""
import io
import json
import os
import subprocess
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import _issue_jwt  # noqa: E402
import fricatives  # noqa: E402

CASES = [("sip", "hannah_sip"), ("zip", "hannah_zip"), ("zoo", "hannah_zoo"), ("sue", "hannah_sue"), ("ship", "hannah_ship"), ("sham", "hannah_sham"),
         ("think", "hannah_think"), ("sink", "hannah_sink"), ("fink", "hannah_fink"), ("fan", "hannah_fan"), ("van", "hannah_van"),
         ("then", "hannah_then"), ("den", "hannah_den"), ("zen", "hannah_zen"), ("vet", "hannah_vet"), ("face", "hannah_face"), ("house", "hannah_house"),
         ("toes", "hannah_toes"), ("yes", "hannah_yes"), ("horse", "hannah_horse"), ("fuss", "hannah_fuss"),
         # error takes assessed against the target word
         ("think", "hannah_fink"), ("zoo", "hannah_sue"), ("sip", "hannah_zip"), ("then", "hannah_zen"), ("then", "hannah_den"),
         ("fan", "hannah_van"), ("van", "hannah_fan"), ("think", "hannah_sink"), ("sip", "hannah_ship")]
CACHE = "/tmp/pt_bank/_windows.json"


def wav(path):
    out = path.replace(".mp3", ".wav")
    if not os.path.exists(out):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out], check=True)
    return open(out, "rb").read()


def main():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    ck = {"accent_session": _issue_jwt(os.environ["ADMIN_EMAILS"].split(",")[0].strip())}
    for word, f in CASES:
        key, p = f"{word}|{f}", f"/tmp/pt_bank/{f}.mp3"
        if not os.path.exists(p):
            continue
        if key not in cache:
            r = httpx.post("http://localhost:8001/api/practice/assess", data={"word": word}, files={"audio": (f, io.BytesIO(open(p, "rb").read()), "audio/mpeg")}, cookies=ck, timeout=120).json()
            if not r.get("phonemes"):
                print(f"{f:>14} as {word:<6} unassessable: {r.get('reason') or r.get('detail')}")
                continue
            cache[key] = [{"expected": q["expected"], "start_s": q["start_s"], "end_s": q["end_s"], "ear": q.get("ear")} for q in r["phonemes"]]
            json.dump(cache, open(CACHE, "w"))
        w = wav(p)
        phs = cache[key]
        for i, ph in enumerate(phs):
            if ph["expected"] in fricatives.CHECKED:
                m = fricatives.measure(w, ph["start_s"], ph["end_s"])
                j = fricatives.judge(ph["expected"], m, i == len(phs) - 1) if m else None
                print(f"{f:>14} as {word:<6} /{ph['expected']}/ {m} ear={str(ph.get('ear')):<9} {'→ ' + j['heard'] if j else 'ok'}")


main()
