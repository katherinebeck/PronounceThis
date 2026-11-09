"""Push /tmp/pt_rhotic clips through /api/practice/assess as admin; print ear + student feedback.

Run: cd /app/backend && python3 tests/run_ear_clips.py [substring filter]
"""
import asyncio
import io
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from auth import _issue_jwt  # noqa: E402

API = os.environ.get("API_URL", "http://localhost:8001") + "/api"
COOKIE = {"accent_session": _issue_jwt(os.environ["ADMIN_EMAILS"].split(",")[0].strip())}


async def main():
    filt = sys.argv[1] if len(sys.argv) > 1 else ""
    files = sorted(f for f in os.listdir("/tmp/pt_rhotic") if f.endswith(".mp3") and filt in f)
    async with httpx.AsyncClient(timeout=120) as c:
        for f in files:
            voice, word = f[:-4].split("_", 1)
            ref = "aluminum" if word == "aluminium" else word
            audio = open(f"/tmp/pt_rhotic/{f}", "rb").read()
            r = await c.post(f"{API}/practice/assess", data={"word": ref}, files={"audio": (f, io.BytesIO(audio), "audio/mpeg")}, cookies=COOKIE)
            b = r.json()
            if r.status_code != 200:
                print(f"{f:>22} HTTP {r.status_code} {b.get('detail')}")
                continue
            ear = b.get("ear") or {}
            checks = " ".join(
                f"{k['expected']}:{k['verdict'][0]}{'' if k['verdict'] == 'confirmed' else '(' + str(k.get('heard')) + ')'}{int((k.get('p_expected') or 0) * 100)}"
                for k in (ear.get("checks") or []))
            tim = " ".join(f"{p['expected']}={(p['end_s'] or 0) - (p['start_s'] or 0):.2f}" for p in b.get("phonemes", []))
            print(f"\n{f:>22} azure={b.get('azure_score')} → {b.get('score10')}/10 {b.get('band')}  heard='{ear.get('heard')}'")
            print(f"{'':>22} ear: {checks}")
            print(f"{'':>22} dur: {tim}  extra_syl={b.get('extra_syllables')} stress={(b.get('stress') or {}).get('verdict')}")
            for n in b.get("needs_work", []):
                tag = "NOT HEARD" if n.get("confirmed") else ("OVERDONE" if n.get("overdone") else ("EXTRA SOUND" if n.get("intrusion") else "weak"))
                print(f"{'':>22}  • /{n['phoneme']}/ {tag} {('→ ' + n['heard']) if n.get('heard') else ''} {n.get('note') or ''}")


asyncio.run(main())
