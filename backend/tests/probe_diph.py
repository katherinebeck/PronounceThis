"""Probe diphthong trajectories: how far F1/F2 travel in clean vs flattened takes.
Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/probe_diph.py"""
import io
import json
import math
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import _issue_jwt  # noqa: E402
from probe_ou import wav  # noqa: E402
import formants  # noqa: E402

CASES = [("house", "hannah_house"), ("house", "hannah_hose"), ("time", "hannah_time"), ("time", "hannah_tom"), ("time", "hannah_tame"),
         ("boy", "hannah_boy"), ("boy", "hannah_buy"), ("day", "hannah_day"), ("face", "hannah_face"), ("right", "hannah_right"),
         ("white", "hannah_white"), ("light", "hannah_light"), ("boat", "hannah_boat"), ("coat", "hannah_coat"), ("goat", "hannah_goat")]
CACHE = "/tmp/pt_bank/_windows.json"
D = {"eɪ", "aɪ", "ɔɪ", "oʊ", "aʊ"}


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
            cache[key] = [{"expected": q["expected"], "start_s": q["start_s"], "end_s": q["end_s"], "ear": q.get("ear"), "ear_p": q.get("ear_p")} for q in r["phonemes"]]
            json.dump(cache, open(CACHE, "w"))
        w = wav(p)
        for ph in cache[key]:
            if ph["expected"] in D and ph["start_s"] is not None:
                t = formants.trajectory(w, ph["start_s"], ph["end_s"])
                if not t:
                    print(f"{f:>14} /{ph['expected']}/ dur={ph['end_s'] - ph['start_s']:.2f} too short")
                    continue
                (a1, a2), (b1, b2) = t
                d1, d2 = math.log(b1 / a1), math.log(b2 / a2)
                print(f"{f:>14} /{ph['expected']}/ dur={ph['end_s'] - ph['start_s']:.2f} ear={ph.get('ear')}:{ph.get('ear_p')} "
                      f"start=({int(a1)},{int(a2)}) end=({int(b1)},{int(b2)}) d1={d1:+.2f} d2={d2:+.2f} move={math.hypot(d1, d2):.2f}")


main()
