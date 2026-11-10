"""Assess one bank clip and print the needs_work + admin readings.
Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/one_clip.py word [clip.mp3 ...]"""
import asyncio
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sound_bank import assess  # noqa: E402
from auth import _issue_jwt  # noqa: E402


async def main() -> None:
    word = sys.argv[1]
    clips = sys.argv[2:] or [f"/tmp/pt_bank/hannah_{word}.mp3"]
    cookies = {"accent_session": _issue_jwt(os.environ["ADMIN_EMAILS"].split(",")[0].strip())}
    async with httpx.AsyncClient(timeout=90) as c:
        for clip in clips:
            b = await assess(c, cookies, word, clip)
            ear = b.get("ear") or {}
            print(clip, b.get("score10"), b.get("band"))
            for n in b.get("needs_work", []):
                print("  NW", json.dumps({k: v for k, v in n.items() if v not in (None, False) and k != "tip"}, ensure_ascii=False))
            print("  heard", ear.get("heard"), "| scale", ear.get("speaker_scale"), "| own_u", ear.get("own_u_f2"))
            print("  checks", [(c["expected"], c["verdict"], c.get("p_expected"), c.get("heard"), c.get("p_heard")) for c in (ear.get("checks") or [])])
            print("  formants", ear.get("formants"), "| fric", ear.get("fricatives"), "| rhotic", ear.get("rhotic"))
            print("  timing", [(t["expected"], t.get("dur"), t.get("ref")) for t in (ear.get("timing") or [])])


asyncio.run(main())
