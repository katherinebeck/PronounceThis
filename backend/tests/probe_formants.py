"""Probe the formant ear on bank clips: prints F1/F2 for each checked vowel and the verdict.

Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/probe_formants.py
Azure windows are cached in /tmp/pt_bank/_windows.json so re-runs are free.
"""
import io
import json
import os
import subprocess
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import _issue_jwt  # noqa: E402
import formants  # noqa: E402

CASES = [("sheep", "hannah_sheep"), ("ship", "hannah_ship"), ("bed", "hannah_bed"), ("cat", "hannah_cat"), ("hat", "hannah_hat"),
         ("fan", "hannah_fan"), ("hot", "hannah_hot"), ("caught", "hannah_caught"), ("book", "hannah_book"), ("food", "hannah_food"),
         ("cup", "hannah_cup"), ("sip", "hannah_sip"), ("think", "hannah_think"), ("pin", "hannah_pin"), ("net", "hannah_net"),
         ("cup", "hannah_cop"), ("hot", "tanya_hot"), ("hot", "hannah_hut"), ("cat", "hannah_cot"), ("bed", "hannah_bad"),
         ("sheep", "hannah_ship"), ("book", "hannah_buck"), ("cup", "hannah_cap"), ("ship", "hannah_sheep"), ("bed", "hannah_bid")]
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
        key = f"{word}|{f}"
        p = f"/tmp/pt_bank/{f}.mp3"
        if key not in cache:
            r = httpx.post("http://localhost:8001/api/practice/assess", data={"word": word}, files={"audio": (f, io.BytesIO(open(p, "rb").read()), "audio/mpeg")}, cookies=ck, timeout=120).json()
            cache[key] = [{"expected": q["expected"], "start_s": q["start_s"], "end_s": q["end_s"], "ear": q.get("ear")} for q in r["phonemes"]]
            json.dump(cache, open(CACHE, "w"))
        w = wav(p)
        for ph in cache[key]:
            if ph["expected"] in formants.CHECKED:
                m = formants.measure(w, ph["start_s"], ph["end_s"])
                j = formants.judge(ph["expected"], m) if m else None
                flag = "ok" if not j else f"→ {j['heard']}"
                m_s, e_s = str(tuple(int(x) for x in m) if m else None), str(ph.get("ear"))
                print(f"{f:>14} as {word:<6} /{ph['expected']}/ F1/F2={m_s:<14} ear={e_s:<9} {flag}")


main()
