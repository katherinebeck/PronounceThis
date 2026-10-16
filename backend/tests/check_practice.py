"""Stage-1 smoke test for /api/practice/assess using cached word clips as fake takes.

Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/check_practice.py
"""
import asyncio
import base64
import io
import json
import os
import struct
import sys

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from auth import _issue_jwt  # noqa: E402

API = os.environ.get("API_URL", "http://localhost:8001") + "/api"
COOKIE = {"accent_session": _issue_jwt("katherine@katherinebeck.com")}


def silence_wav(seconds=1.5, rate=16000):
    n = int(seconds * rate)
    data = b"\x00\x00" * n
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data))
    return hdr + data


async def clip(db, word):
    doc = await db.audio_cache.find_one({"word": word}, {"_id": 0, "audio_b64": 1, "content_type": 1})
    return base64.b64decode(doc["audio_b64"]), doc.get("content_type") or "audio/mpeg"


async def assess(client, word, audio, mime, name="take.mp3"):
    r = await client.post(f"{API}/practice/assess", data={"word": word},
                          files={"audio": (name, io.BytesIO(audio), mime)}, cookies=COOKIE, timeout=60)
    body = r.json()
    short = {k: body.get(k) for k in ("assessable", "reason", "recognized", "score", "accuracy", "band", "detail")}
    short["needs_work"] = [(n["phoneme"], n["score"], n["heard"]) for n in body.get("needs_work", [])]
    short["accurate"] = body.get("accurate")
    print(f"\n[{word}] HTTP {r.status_code}\n{json.dumps(short, ensure_ascii=False, indent=1)}")
    return r.status_code, body


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    async with httpx.AsyncClient() as c:
        st = (await c.get(f"{API}/practice/status")).json()
        print("status:", st)
        assert st["enabled"]
        party, mime = await clip(db, "party")
        code, b = await assess(c, "party", party, mime)
        assert code == 200 and b["assessable"] and b["score"] >= 70 and b["accurate"], "good clip should score well"
        story, m2 = await clip(db, "story")
        await assess(c, "store", story, m2)  # near-miss: expect partial phoneme scores
        dm, m3 = await clip(db, "des moines")
        code, b = await assess(c, "des moines", dm, m3)
        assert code == 200 and b["assessable"], "phrase should be assessable"
        code, b = await assess(c, "whole", party, mime)
        assert code == 200 and (not b["assessable"] or b["score"] < 60), "wrong word should score low / be rejected"
        code, b = await assess(c, "party", silence_wav(), "audio/wav", "s.wav")
        assert code == 200 and not b["assessable"], "silence must not be scored"
        code, b = await assess(c, "party", b"garbage" * 100, "audio/webm", "x.webm")
        assert code == 415, "undecodable audio → 415"
        code, b = await assess(c, "bad word!!", party, mime)
        assert code == 400
        r = await c.post(f"{API}/practice/assess", data={"word": "party"},
                         files={"audio": ("t.mp3", io.BytesIO(party), mime)})
        print("\nno auth →", r.status_code)
        assert r.status_code == 401
    print("\nALL OK")


asyncio.run(main())
