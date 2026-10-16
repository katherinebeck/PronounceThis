"""Hybrid check: push British (dropped-R) and American control clips through /api/practice/assess
as the admin and print the ear readout + adjusted score.

Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/check_ear.py
"""
import asyncio
import io
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from auth import _issue_jwt  # noqa: E402

API = os.environ.get("API_URL", "http://localhost:8001") + "/api"
COOKIE = {"accent_session": _issue_jwt("katherine@katherinebeck.com")}
CLIPS = [  # (file, reference word, expectation)
    ("hannah_party.mp3", "party", "clean"), ("george_party.mp3", "party", "R missing"), ("lily_party.mp3", "party", "R missing"),
    ("george_word.mp3", "word", "R missing"), ("lily_word.mp3", "word", "R missing"),
    ("ctl_father.mp3", "father", "clean"), ("ctl_george.mp3", "george", "clean"), ("ctl_whole.mp3", "whole", "clean"),
    ("ctl_tour.mp3", "tour", "clean"), ("hannah_story.mp3", "story", "clean"), ("hannah_need.mp3", "need", "clean"),
    ("flap_city.mp3", "city", "clean"), ("flap_butter.mp3", "butter", "clean"), ("flap_water.mp3", "water", "clean"),
    ("flap_better.mp3", "better", "clean"), ("flap_pretty.mp3", "pretty", "clean"), ("flap_little.mp3", "little", "clean"),
    ("hardT_city.mp3", "city", "hard T"), ("hardT_butter.mp3", "butter", "hard T"), ("hardT_water.mp3", "water", "hard T+R"),
    ("hardT_better.mp3", "better", "hard T+R"), ("hardT_pretty.mp3", "pretty", "hard T"), ("hardT_little.mp3", "little", "hard T"),
]


async def main():
    async with httpx.AsyncClient(timeout=90) as c:
        for f, word, expect in CLIPS:
            audio = open(f"/tmp/pt_rhotic/{f}", "rb").read()
            r = await c.post(f"{API}/practice/assess", data={"word": word}, files={"audio": (f, io.BytesIO(audio), "audio/mpeg")}, cookies=COOKIE)
            b = r.json()
            if r.status_code != 200:
                print(f"{f:>18} HTTP {r.status_code} {b.get('detail')}")
                continue
            ear = b.get("ear") or {}
            checks = " ".join(f"{k['expected']}:{k['verdict'][0]}{'' if k['verdict']=='confirmed' else '('+str(k.get('heard'))+')'}" for k in (ear.get("checks") or []))
            flagged = [f"{n['phoneme']}{'*' if n.get('confirmed') else ''}" for n in b.get("needs_work", [])]
            print(f"{f:>18} [{expect:>9}] azure={b.get('azure_score')} → {b.get('score10')}/10 {b.get('band'):<13} heard='{ear.get('heard')}'  {checks}  flagged={flagged}")


asyncio.run(main())
