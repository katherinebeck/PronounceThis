"""Backend tests for speaker-turn detection and turn-level TTS."""
import io
import os

import pytest
import requests
from reportlab.pdfgen import canvas

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

EXISTING_SCENE_ID = "4b23e55d-67be-42bc-a397-4eb4085bdb2e"


# ---------- helpers ---------------------------------------------------------
def _pdf_from_lines(lines):
    """Render each string as its own PDF line so pypdf reconstructs newlines."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for ln in lines:
        c.drawString(72, y, ln)
        y -= 24
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def _upload(session, lines, title="turn-test"):
    files = {"file": (f"{title}.pdf", _pdf_from_lines(lines), "application/pdf")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=120)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def session():
    return requests.Session()


# ---------- turn detection: inline style -----------------------------------
@pytest.fixture(scope="module")
def inline_scene(session):
    lines = [
        "JANE: I want a little butter on my bread, mother. "
        "MARK: Better hurry, darling. The water is getting cold. "
        "JANE: Are you sure?"
    ]
    data = _upload(session, lines, "inline")
    yield data
    session.delete(f"{API}/scenes/{data['id']}")


def test_inline_turns_structure(inline_scene):
    turns = inline_scene.get("turns")
    assert isinstance(turns, list) and len(turns) == 3, f"expected 3 turns got {turns}"
    speakers = [t["speaker"] for t in turns]
    assert speakers == ["JANE", "MARK", "JANE"], f"got {speakers}"
    # indexes are sequential
    assert [t["index"] for t in turns] == [0, 1, 2]
    # bodies contain the right content, not the speaker label
    assert "butter" in turns[0]["text"].lower()
    assert not turns[0]["text"].startswith("JANE")
    assert "hurry" in turns[1]["text"].lower()
    assert "sure" in turns[2]["text"].lower()


def test_dialogue_words_have_int_turn_index(inline_scene):
    """With dialogue-only extraction, speaker-label words (JANE, MARK) are
    stripped entirely from the token stream — only spoken words remain, each
    with an int turn_index."""
    tokens = inline_scene["tokens"]
    for t in tokens:
        if t.get("is_word"):
            assert "turn_index" in t
            assert isinstance(t["turn_index"], int), (
                f"dialogue word missing int turn_index: {t}"
            )
    # 'butter' is dialogue -> present with an int turn_index
    butter = next(t for t in tokens if t.get("is_word")
                  and t["text"].lower().strip(",.") == "butter")
    assert isinstance(butter["turn_index"], int)
    # JANE label word should NOT appear as a token (LLM promotes to speaker).
    word_texts = {t["text"] for t in tokens if t.get("is_word")}
    assert "JANE" not in word_texts and "MARK" not in word_texts


# ---------- turn detection: screenplay style -------------------------------
@pytest.fixture(scope="module")
def screenplay_scene(session):
    # Speaker on its own line, dialogue on next line(s).
    lines = [
        "ROMEO",
        "But soft.",
        "JULIET",
        "What light?",
        "ROMEO",
        "A rose.",
    ]
    data = _upload(session, lines, "screenplay")
    yield data
    session.delete(f"{API}/scenes/{data['id']}")


def test_screenplay_turns(screenplay_scene):
    turns = screenplay_scene["turns"]
    speakers = [t["speaker"] for t in turns]
    # Expect 3 merged turns: ROMEO / JULIET / ROMEO
    # (the two ROMEO blocks are separated by JULIET so they stay separate,
    # but each ROMEO's own lines must be its own single turn)
    assert speakers == ["ROMEO", "JULIET", "ROMEO"], f"got {speakers} turns={turns}"
    assert "soft" in turns[0]["text"].lower()
    assert "light" in turns[1]["text"].lower()
    assert "rose" in turns[2]["text"].lower()


# ---------- consecutive-same-speaker merging -------------------------------
@pytest.fixture(scope="module")
def merge_scene(session):
    # Two consecutive ROMEO screenplay blocks with no other speaker between
    lines = [
        "ROMEO",
        "But soft.",
        "ROMEO",
        "A rose by any name.",
        "JULIET",
        "What light?",
    ]
    data = _upload(session, lines, "merge")
    yield data
    session.delete(f"{API}/scenes/{data['id']}")


def test_consecutive_same_speaker_merged(merge_scene):
    turns = merge_scene["turns"]
    speakers = [t["speaker"] for t in turns]
    assert speakers == ["ROMEO", "JULIET"], f"got {speakers}"
    # Both ROMEO lines merged into one text
    assert "soft" in turns[0]["text"].lower()
    assert "rose" in turns[0]["text"].lower()


# ---------- existing scene (Little House) ---------------------------------
def test_existing_scene_has_turns(session):
    r = session.get(f"{API}/scenes/{EXISTING_SCENE_ID}", timeout=15)
    if r.status_code == 404:
        pytest.skip("Little House seed scene not present")
    assert r.status_code == 200
    data = r.json()
    turns = data.get("turns")
    assert isinstance(turns, list) and len(turns) >= 1
    # Speaker labels for known scene per problem statement include NARRATION
    # etc. We just verify structure + that at least one has a speaker.
    assert any(t.get("speaker") for t in turns)
    for t in turns:
        assert set(t.keys()) >= {"index", "speaker", "text"}
        assert isinstance(t["index"], int)
        assert t["text"].strip()


# ---------- Turn TTS endpoint ---------------------------------------------
def test_turn_tts_happy_path_and_cache(session, inline_scene):
    sid = inline_scene["id"]
    r1 = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=90)
    # Paid key expected -> 200; also accept 502 (upstream) with a clear detail
    assert r1.status_code in (200, 502), r1.text
    if r1.status_code == 502:
        pytest.skip(f"ElevenLabs upstream failure: {r1.json().get('detail')}")

    body1 = r1.json()
    assert body1["scene_id"] == sid
    assert body1["turn_index"] == 0
    assert body1["speaker"] == "JANE"
    assert body1["mime"] == "audio/mpeg"
    assert body1["cached"] is False
    assert isinstance(body1["audio_b64"], str) and len(body1["audio_b64"]) > 100

    # Second call should be cached
    r2 = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=30)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["cached"] is True
    assert body2["audio_b64"] == body1["audio_b64"]


def test_turn_tts_invalid_scene(session):
    r = session.post(f"{API}/scenes/does-not-exist/turns/0/tts", timeout=15)
    assert r.status_code == 404


def test_turn_tts_out_of_range(session, inline_scene):
    sid = inline_scene["id"]
    n = len(inline_scene["turns"])
    r = session.post(f"{API}/scenes/{sid}/turns/{n + 5}/tts", timeout=15)
    assert r.status_code == 404
    r2 = session.post(f"{API}/scenes/{sid}/turns/-1/tts", timeout=15)
    # FastAPI parses -1 as int and app-level check returns 404
    assert r2.status_code in (404, 422)
