"""Pronounce This — ear service. Hosts the phoneme recogniser so the main backend stays light.

GET  /health  → {"ready": bool, "model": ..., "status": ...}
POST /listen  → body {"wav_b64": <16 kHz mono PCM wav>, "windows": [{expected, start_s, end_s, flap}]}
Both require header X-Ear-Secret matching EAR_SECRET.
"""
import base64
import os
import sys

from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phoneme_ear  # noqa: E402

SECRET = os.environ["EAR_SECRET"]
app = FastAPI(title="Pronounce This ear", docs_url=None, redoc_url=None)


class ListenRequest(BaseModel):
    wav_b64: str
    windows: list


def _auth(secret: str) -> None:
    if secret != SECRET:
        raise HTTPException(status_code=401, detail="bad secret")


@app.on_event("startup")
def _startup() -> None:
    phoneme_ear._load()


@app.get("/health")
def health(x_ear_secret: str = Header(default="")):
    _auth(x_ear_secret)
    return {"ready": phoneme_ear.available(), **phoneme_ear.status()}


@app.post("/listen")
async def listen(req: ListenRequest, x_ear_secret: str = Header(default="")):
    _auth(x_ear_secret)
    if not phoneme_ear.available():
        raise HTTPException(status_code=503, detail=phoneme_ear.status())
    try:
        wav = base64.b64decode(req.wav_b64)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="wav_b64 is not base64")
    if len(wav) > 2_000_000:
        raise HTTPException(status_code=413, detail="clip too long")
    out = await run_in_threadpool(phoneme_ear.listen, wav, req.windows)
    return out or {}
