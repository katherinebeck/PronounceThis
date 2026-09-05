"""Tests for GET /api/scenes/{id}/download-lines (Download My Lines ZIP)."""
import io
import os
import time
import zipfile

import pytest
import requests
from reportlab.pdfgen import canvas

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _pdf(lines):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for ln in lines:
        c.drawString(72, y, ln)
        y -= 24
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture(scope="module")
def session():
    return requests.Session()


@pytest.fixture(scope="module")
def scene(session):
    r = session.get(f"{API}/scenes", timeout=30)
    assert r.status_code == 200
    for s in r.json():
        detail = session.get(f"{API}/scenes/{s['id']}", timeout=30).json()
        turns = detail.get("turns") or []
        speakers = {(t.get("speaker") or "").strip() for t in turns}
        speakers.discard("")
        if len(turns) >= 2 and speakers:
            return detail
    # upload one
    lines = [
        "JANE: Hello there friend.",
        "MARK: How are you today.",
        "JANE: I am doing quite well.",
        "MARK: Glad to hear that.",
    ]
    files = {"file": ("dl.pdf", _pdf(lines), "application/pdf")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=180)
    assert r.status_code == 200, r.text
    return r.json()


def _char(scene):
    for t in scene["turns"]:
        sp = (t.get("speaker") or "").strip()
        if sp:
            return sp
    raise AssertionError("No speaker in scene")


def _valid_mp3(b: bytes) -> bool:
    if len(b) < 1024:
        return False
    return b.startswith(b"ID3") or (len(b) >= 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0)


def test_download_lines_ok(session, scene):
    ch = _char(scene)
    r = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                    params={"character": ch}, timeout=180)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    disp = r.headers.get("content-disposition", "")
    assert "attachment" in disp and ".zip" in disp

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert names, "empty ZIP"
    # naming NN_...mp3
    for i, name in enumerate(names, start=1):
        assert name.endswith(".mp3")
        assert name.startswith(f"{i:02d}_")
        data = zf.read(name)
        assert _valid_mp3(data), f"{name} not a valid mp3 ({len(data)} bytes)"


def test_download_lines_voice_cache(session, scene):
    ch = _char(scene)
    sid = scene["id"]

    t0 = time.time()
    r1 = session.get(f"{API}/scenes/{sid}/download-lines",
                     params={"character": ch, "voice": "jessica"}, timeout=180)
    t1 = time.time() - t0
    assert r1.status_code == 200, r1.text
    assert r1.headers["content-type"].startswith("application/zip")

    t0 = time.time()
    r2 = session.get(f"{API}/scenes/{sid}/download-lines",
                     params={"character": ch, "voice": "jessica"}, timeout=60)
    t2 = time.time() - t0
    assert r2.status_code == 200
    # second call should be much faster (cached)
    assert t2 < max(5.0, t1 * 0.6), f"cache didn't help: t1={t1:.2f}s t2={t2:.2f}s"

    # adam separate cache -> different bytes
    ra = session.get(f"{API}/scenes/{sid}/download-lines",
                     params={"character": ch, "voice": "adam"}, timeout=180)
    assert ra.status_code == 200
    assert ra.content != r1.content


def test_download_lines_bad_voice(session, scene):
    ch = _char(scene)
    r = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                    params={"character": ch, "voice": "badvoice"}, timeout=15)
    assert r.status_code == 400
    assert r.json()["detail"] == "Unknown voice."


def test_download_lines_unknown_character(session, scene):
    r = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                    params={"character": "DoesNotExist"}, timeout=15)
    assert r.status_code == 404
    assert "No lines found" in r.json()["detail"]


def test_download_lines_missing_scene(session):
    r = session.get(f"{API}/scenes/nope-not-real/download-lines",
                    params={"character": "X"}, timeout=15)
    assert r.status_code == 404
    assert r.json()["detail"] == "Scene not found"
