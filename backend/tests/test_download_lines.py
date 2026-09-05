"""Tests for GET /api/scenes/{id}/download-lines.

Iteration 13: response is now a SINGLE concatenated MP3 with a silent gap
between each of the character's lines (default 2000ms), configurable via
`gap_ms` (clamped 0..10000).
"""
import io
import os
import time

import pytest
import requests
from pydub import AudioSegment
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
    # Prefer the known cached scene for speed
    known_id = "4b23e55d-67be-42bc-a397-4eb4085bdb2e"
    r = session.get(f"{API}/scenes/{known_id}", timeout=30)
    if r.status_code == 200:
        detail = r.json()
        turns = detail.get("turns") or []
        speakers = {(t.get("speaker") or "").strip() for t in turns}
        speakers.discard("")
        if turns and speakers:
            return detail

    r = session.get(f"{API}/scenes", timeout=30)
    assert r.status_code == 200
    for s in r.json():
        detail = session.get(f"{API}/scenes/{s['id']}", timeout=30).json()
        turns = detail.get("turns") or []
        speakers = {(t.get("speaker") or "").strip() for t in turns}
        speakers.discard("")
        if len(turns) >= 2 and speakers:
            return detail
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
    # prefer ELIZA (cached) if available, else first speaker
    for t in scene["turns"]:
        if (t.get("speaker") or "").strip() == "ELIZA":
            return "ELIZA"
    for t in scene["turns"]:
        sp = (t.get("speaker") or "").strip()
        if sp:
            return sp
    raise AssertionError("No speaker in scene")


def _count_char_lines(scene, ch):
    return sum(1 for t in scene["turns"] if (t.get("speaker") or "").strip() == ch)


def _valid_mp3(b: bytes) -> bool:
    if len(b) < 1024:
        return False
    return b.startswith(b"ID3") or (len(b) >= 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0)


def _duration_ms(b: bytes) -> int:
    seg = AudioSegment.from_file(io.BytesIO(b), format="mp3")
    return len(seg)


def test_download_lines_ok_single_mp3(session, scene):
    ch = _char(scene)
    r = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                    params={"character": ch}, timeout=300)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/mpeg")
    disp = r.headers.get("content-disposition", "")
    assert "attachment" in disp and ".mp3" in disp and ".zip" not in disp
    assert _valid_mp3(r.content), f"not a valid MP3 ({len(r.content)} bytes)"


def test_download_lines_gap_default_2s(session, scene):
    ch = _char(scene)
    n = _count_char_lines(scene, ch)
    # Default gap = 2000ms
    r_def = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                        params={"character": ch}, timeout=300)
    assert r_def.status_code == 200
    d_def = _duration_ms(r_def.content)

    r0 = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                     params={"character": ch, "gap_ms": 0}, timeout=300)
    assert r0.status_code == 200
    d0 = _duration_ms(r0.content)

    expected_extra = 2000 * max(0, n - 1)
    diff = d_def - d0
    # allow ±400ms tolerance for MP3 frame boundary rounding
    assert abs(diff - expected_extra) <= 400, (
        f"expected ~{expected_extra}ms extra silence, got {diff}ms (n={n})"
    )


def test_download_lines_gap_clamped(session, scene):
    ch = _char(scene)
    n = _count_char_lines(scene, ch)
    if n < 2:
        pytest.skip("need at least 2 lines for gap comparison")
    r0 = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                     params={"character": ch, "gap_ms": 0}, timeout=300)
    r1 = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                     params={"character": ch, "gap_ms": 1000}, timeout=300)
    r15 = session.get(f"{API}/scenes/{scene['id']}/download-lines",
                      params={"character": ch, "gap_ms": 15000}, timeout=300)
    assert r0.status_code == r1.status_code == r15.status_code == 200
    d0 = _duration_ms(r0.content)
    d1 = _duration_ms(r1.content)
    d15 = _duration_ms(r15.content)

    exp1 = 1000 * (n - 1)
    exp15 = 10000 * (n - 1)  # clamped to 10s
    assert abs((d1 - d0) - exp1) <= 400
    assert abs((d15 - d0) - exp15) <= 500


def test_download_lines_voice_cache(session, scene):
    ch = _char(scene)
    sid = scene["id"]

    t0 = time.time()
    r1 = session.get(f"{API}/scenes/{sid}/download-lines",
                     params={"character": ch, "voice": "jessica"}, timeout=300)
    t1 = time.time() - t0
    assert r1.status_code == 200
    assert r1.headers["content-type"].startswith("audio/mpeg")

    t0 = time.time()
    r2 = session.get(f"{API}/scenes/{sid}/download-lines",
                     params={"character": ch, "voice": "jessica"}, timeout=120)
    t2 = time.time() - t0
    assert r2.status_code == 200
    assert t2 < max(10.0, t1 * 0.7), f"cache didn't help: t1={t1:.2f}s t2={t2:.2f}s"


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
