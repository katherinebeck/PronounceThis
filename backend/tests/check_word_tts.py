"""Manual check: render single words via /api/tts and transcribe with Whisper."""
import asyncio, base64, json, os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from auth import _issue_jwt  # noqa: E402
from line_check import transcribe  # noqa: E402

API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0]
JWT = _issue_jwt("katherine@katherinebeck.com")


def tts(word: str) -> bytes:
    req = urllib.request.Request(f"{API}/api/tts", data=json.dumps({"word": word}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "curl/8", "Cookie": f"accent_session={JWT}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    return base64.b64decode(d["audio_b64"]), d["cached"]


async def main():
    for w in sys.argv[1:] or ["I", "this", "party", "need", "oner"]:
        audio, cached = tts(w)
        heard = await transcribe(audio)
        print(f"{w:>8} cached={cached!s:5} bytes={len(audio):6} heard={heard!r}")

asyncio.run(main())
