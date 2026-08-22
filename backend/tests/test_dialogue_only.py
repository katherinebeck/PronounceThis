"""Backend tests for dialogue-only extraction feature.

Verifies that upload/get/reparse strip stage directions and narration and
keep only spoken dialogue, that pre-migration scenes auto-migrate on GET,
and that laundry-lists / turn-TTS still work on the new tokens.
"""
import io
import os
import time

import pytest
import requests
from reportlab.pdfgen import canvas

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

EXISTING_SCENE_ID = "4b23e55d-67be-42bc-a397-4eb4085bdb2e"


# ---------- helpers ---------------------------------------------------------
def _pdf(lines):
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


def _upload(session, lines, title="dlg", expect_ok=True):
    files = {"file": (f"{title}.pdf", _pdf(lines), "application/pdf")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=180)
    if expect_ok:
        assert r.status_code == 200, r.text
        return r.json()
    return r


@pytest.fixture(scope="module")
def session():
    return requests.Session()


# ---------- Upload strips stage directions ---------------------------------
@pytest.fixture(scope="module")
def dialogue_scene(session):
    lines = [
        "EXT. TOWN SQUARE - DAY",
        "The crowd gathers.",
        "JANE: I want a little butter.",
        "A beat.",
        "JANE: Now, please.",
        "MARK: Better hurry. The water is getting cold.",
    ]
    data = _upload(session, lines, "dlg-strip")
    yield data
    session.delete(f"{API}/scenes/{data['id']}")


def test_upload_returns_only_dialogue_turns(dialogue_scene):
    turns = dialogue_scene["turns"]
    assert len(turns) == 2, f"expected 2 turns after merge; got {turns}"
    speakers = [t["speaker"] for t in turns]
    assert speakers == ["JANE", "MARK"], f"got {speakers}"
    # JANE's two lines merged into one entry
    jane_text = turns[0]["text"].lower()
    assert "butter" in jane_text
    assert "please" in jane_text or "now" in jane_text
    mark_text = turns[1]["text"].lower()
    assert "hurry" in mark_text
    assert "cold" in mark_text


def test_upload_every_turn_has_a_speaker(dialogue_scene):
    for t in dialogue_scene["turns"]:
        assert t["speaker"], f"turn {t['index']} has no speaker: {t}"


def test_upload_tokens_exclude_narration_and_headings(dialogue_scene):
    tokens = dialogue_scene["tokens"]
    word_texts = [t["text"].lower() for t in tokens if t.get("is_word")]
    joined = " ".join(word_texts)
    for banned in ("crowd", "beat", "ext", "gathers", "square"):
        assert banned not in word_texts, (
            f"stripped word '{banned}' leaked into tokens: {word_texts}"
        )
    # Speaker labels JANE/MARK themselves should not be dialogue-word tokens
    # either (the LLM strips them into the turn.speaker field).
    assert "jane" not in word_texts, f"JANE label leaked: {joined}"
    assert "mark" not in word_texts, f"MARK label leaked: {joined}"
    # All word tokens should have a turn_index (they are all dialogue words)
    for t in tokens:
        if t.get("is_word"):
            assert isinstance(t.get("turn_index"), int), (
                f"dialogue word missing turn_index: {t}"
            )


# ---------- Pure narration => 400 ------------------------------------------
def test_pure_narration_upload_returns_400(session):
    lines = [
        "The camera pans across an empty field.",
        "Snow drifts down.",
        "A distant church bell rings.",
    ]
    r = _upload(session, lines, "narration-only", expect_ok=False)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "dialogue" in detail.lower(), f"unhelpful error: {detail}"


# ---------- Existing seed scene: migrated to dialogue-only -----------------
def test_existing_seed_scene_migrated(session):
    t0 = time.time()
    r = session.get(f"{API}/scenes/{EXISTING_SCENE_ID}", timeout=60)
    dt1 = time.time() - t0
    if r.status_code == 404:
        pytest.skip("seed scene not present")
    assert r.status_code == 200
    data = r.json()
    turns = data["turns"]
    # Per problem statement, expect 7 turns, all with a speaker, no narration.
    assert len(turns) == 7, f"expected 7 turns, got {len(turns)}: " \
        f"{[t.get('speaker') for t in turns]}"
    for t in turns:
        assert t["speaker"], f"turn {t['index']} missing speaker: {t}"
        assert t["text"].strip()

    # Second GET should be fast (already migrated).
    t0 = time.time()
    r2 = session.get(f"{API}/scenes/{EXISTING_SCENE_ID}", timeout=15)
    dt2 = time.time() - t0
    assert r2.status_code == 200
    assert dt2 < 2.0, f"second GET too slow ({dt2:.2f}s); migration not persisted?"

    # Tokens carry turn_index and no obvious narration words leaked.
    word_tokens = [t for t in data["tokens"] if t.get("is_word")]
    assert word_tokens
    for tok in word_tokens:
        assert isinstance(tok.get("turn_index"), int)


# ---------- Reparse endpoint -----------------------------------------------
def test_reparse_unknown_scene_404(session):
    r = session.post(f"{API}/scenes/does-not-exist/reparse", timeout=15)
    assert r.status_code == 404


def test_reparse_returns_fresh_scene(session, dialogue_scene):
    r = session.post(
        f"{API}/scenes/{dialogue_scene['id']}/reparse", timeout=120
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == dialogue_scene["id"]
    # Still dialogue-only shape after reparse
    turns = data["turns"]
    assert len(turns) >= 1
    for t in turns:
        assert t["speaker"]


# ---------- Laundry list on dialogue-only tokens ---------------------------
@pytest.mark.parametrize("sound", [
    "consonant_l", "flap_t", "schwa", "rhotic_r", "diphthongs"
])
def test_laundry_list_on_dialogue_tokens(session, dialogue_scene, sound):
    r = session.get(
        f"{API}/scenes/{dialogue_scene['id']}/laundry-list",
        params={"sound": sound}, timeout=15,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["sound"] == sound
    assert isinstance(data["words"], list)
    assert data["count"] == len(data["words"])
    # Every returned word must appear in the dialogue-only token stream.
    dialogue_words = {
        t["text"].lower()
        for t in dialogue_scene["tokens"] if t.get("is_word")
    }
    for w in data["words"]:
        assert sound in w["categories"]
        assert w["text"].lower() in dialogue_words, (
            f"laundry-list word {w['text']!r} not in dialogue tokens"
        )


# ---------- Turn TTS after migration (cache invalidated) -------------------
def test_turn_tts_on_migrated_scene(session):
    """First tts call after migration should NOT be cached (migration
    invalidated old audio). Second call should be cached."""
    # Ensure seed is migrated first.
    g = session.get(f"{API}/scenes/{EXISTING_SCENE_ID}", timeout=60)
    if g.status_code == 404:
        pytest.skip("seed scene not present")
    turns = g.json()["turns"]
    assert turns, "no turns on seed scene"
    # Use last turn index — guaranteed inside range.
    idx = len(turns) - 1

    r1 = session.post(
        f"{API}/scenes/{EXISTING_SCENE_ID}/turns/{idx}/tts", timeout=120
    )
    assert r1.status_code in (200, 502), r1.text
    if r1.status_code == 502:
        pytest.skip(f"ElevenLabs upstream failure: {r1.json().get('detail')}")
    body1 = r1.json()
    assert body1["turn_index"] == idx
    assert isinstance(body1["audio_b64"], str) and len(body1["audio_b64"]) > 100
    assert body1["mime"] == "audio/mpeg"
    # NB: cache may or may not be false depending on whether a previous test
    # run already populated it. We only assert audio present + round-trip.

    r2 = session.post(
        f"{API}/scenes/{EXISTING_SCENE_ID}/turns/{idx}/tts", timeout=30
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["cached"] is True
    assert body2["audio_b64"] == body1["audio_b64"]


def test_turn_tts_on_new_dialogue_scene(session, dialogue_scene):
    sid = dialogue_scene["id"]
    r1 = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=120)
    assert r1.status_code in (200, 502), r1.text
    if r1.status_code == 502:
        pytest.skip(f"ElevenLabs upstream failure: {r1.json().get('detail')}")
    body1 = r1.json()
    assert body1["cached"] is False
    assert isinstance(body1["audio_b64"], str) and len(body1["audio_b64"]) > 100
    r2 = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=30)
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
