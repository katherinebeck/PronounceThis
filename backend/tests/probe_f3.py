"""Probe the r-colouring (F3) ear on bank clips: F3 over the whole window vs the final 60 %.
Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/probe_f3.py"""
import io
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import _issue_jwt  # noqa: E402
from probe_formants import wav  # noqa: E402
import formants  # noqa: E402

CASES = [("mother", "hannah_mother"), ("mother", "george_mother"), ("bird", "hannah_bird"), ("bird", "george_bird"),
         ("car", "hannah_car"), ("car", "george_car")]
CACHE = "/tmp/pt_bank/_windows.json"
R = {"ɝ", "ɚ", "ɑɹ", "ɔɹ", "ɛɹ", "ɪɹ", "ʊɹ"}


def main():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    ck = {"accent_session": _issue_jwt(os.environ["ADMIN_EMAILS"].split(",")[0].strip())}
    for word, f in CASES:
        key = f"{word}|{f}"
        p = f"/tmp/pt_bank/{f}.mp3"
        if key not in cache:
            r = httpx.post("http://localhost:8001/api/practice/assess", data={"word": word}, files={"audio": (f, io.BytesIO(open(p, "rb").read()), "audio/mpeg")},
                           cookies=ck, headers={"X-Practice-Bank": "1"}, timeout=120).json()
            cache[key] = [{"expected": q["expected"], "start_s": q["start_s"], "end_s": q["end_s"], "ear": q.get("ear")} for q in r["phonemes"]]
            json.dump(cache, open(CACHE, "w"))
        w = wav(p)
        for ph in cache[key]:
            if ph["expected"] in R and ph["start_s"] is not None:
                s, e = ph["start_s"], ph["end_s"]
                whole = formants.f3_median(w, s, e)
                tail = formants.f3_median(w, s + 0.4 * (e - s), e)
                print(f"{f:>14} /{ph['expected']}/ dur={e - s:.2f} F3 whole={whole and round(whole)} tail60={tail and round(tail)}")


main()
