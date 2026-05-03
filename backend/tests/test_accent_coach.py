"""Backend tests for American Accent Coach API."""
import io
import os
import time

import pytest
import requests
from reportlab.pdfgen import canvas

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SAMPLE = ("JANE: I want a little butter on my bread, mother. "
          "MARK: Better hurry, darling. The water is getting cold.")


@pytest.fixture(scope="session")
def sample_pdf_bytes():
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    # Reportlab default font handles ASCII; split into lines
    y = 800
    for line in SAMPLE.split(". "):
        c.drawString(72, y, line)
        y -= 24
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    return s


@pytest.fixture(scope="session")
def uploaded_scene(session, sample_pdf_bytes):
    files = {"file": ("test_scene.pdf", sample_pdf_bytes, "application/pdf")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "id" in data and "tokens" in data
    yield data
    # cleanup
    session.delete(f"{API}/scenes/{data['id']}")


# --- Health -----------------------------------------------------------------
def test_root(session):
    r = session.get(f"{API}/", timeout=10)
    assert r.status_code == 200
    assert r.json().get("message") == "American Accent Coach API"


# --- Sound categories -------------------------------------------------------
def test_sound_categories(session):
    r = session.get(f"{API}/sound-categories", timeout=10)
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert len(cats) == 19
    for c in cats:
        for k in ("id", "label", "ipa", "description"):
            assert k in c
    ids = {c["id"] for c in cats}
    for needed in ("rhotic_r", "light_l", "dark_l", "flap_t",
                   "schwa", "diphthongs", "consonant_l", "consonant_t"):
        assert needed in ids


# --- Upload -----------------------------------------------------------------
def test_upload_rejects_non_pdf(session):
    files = {"file": ("foo.txt", b"hello", "text/plain")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=30)
    assert r.status_code == 400


def test_upload_returns_tokens(uploaded_scene):
    tokens = uploaded_scene["tokens"]
    word_tokens = [t for t in tokens if t.get("is_word")]
    assert len(word_tokens) > 5
    # At least one token from CMU
    has_ipa = [t for t in word_tokens if t.get("ipa")]
    assert len(has_ipa) > 0
    for t in has_ipa[:3]:
        assert "categories" in t
        assert "arpabet" in t
        assert t.get("source") in ("cmu", "llm")


def test_phonetic_correctness_butter(uploaded_scene):
    tokens = [t for t in uploaded_scene["tokens"] if t.get("is_word")]
    butter = next((t for t in tokens if t["text"].lower().strip(",.:;'") == "butter"), None)
    assert butter is not None, "butter token not found"
    assert butter["ipa"] is not None
    # IPA: bˈʌtɝ
    assert "ʌ" in butter["ipa"]
    assert "ɝ" in butter["ipa"]
    cats = butter["categories"]
    for c in ("rhotic_r", "flap_t", "consonant_t"):
        assert c in cats, f"butter missing category {c}; got {cats}"


def test_phonetic_correctness_little(uploaded_scene):
    tokens = [t for t in uploaded_scene["tokens"] if t.get("is_word")]
    little = next((t for t in tokens if t["text"].lower().strip(",.:;'") == "little"), None)
    assert little is not None
    cats = little["categories"]
    for c in ("light_l", "dark_l", "flap_t", "consonant_l"):
        assert c in cats, f"little missing {c}; got {cats}"


# --- List / Get / Delete ----------------------------------------------------
def test_list_scenes(session, uploaded_scene):
    r = session.get(f"{API}/scenes", timeout=15)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    ids = [it["id"] for it in items]
    assert uploaded_scene["id"] in ids
    me = next(it for it in items if it["id"] == uploaded_scene["id"])
    assert me["word_count"] > 0
    assert "title" in me and "created_at" in me
    # Sorted newest first
    if len(items) >= 2:
        assert items[0]["created_at"] >= items[-1]["created_at"]


def test_get_scene(session, uploaded_scene):
    r = session.get(f"{API}/scenes/{uploaded_scene['id']}", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == uploaded_scene["id"]
    assert len(data["tokens"]) == len(uploaded_scene["tokens"])


def test_get_scene_not_found(session):
    r = session.get(f"{API}/scenes/does-not-exist-xyz", timeout=10)
    assert r.status_code == 404


# --- Laundry list -----------------------------------------------------------
@pytest.mark.parametrize("sound", [
    "consonant_l", "flap_t", "schwa", "rhotic_r", "dark_l", "light_l", "diphthongs"
])
def test_laundry_list(session, uploaded_scene, sound):
    r = session.get(f"{API}/scenes/{uploaded_scene['id']}/laundry-list",
                    params={"sound": sound}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["sound"] == sound
    assert isinstance(data["words"], list)
    assert data["count"] == len(data["words"])
    for w in data["words"]:
        assert sound in w["categories"]


def test_laundry_list_flap_t_contains_known(session, uploaded_scene):
    r = session.get(f"{API}/scenes/{uploaded_scene['id']}/laundry-list",
                    params={"sound": "flap_t"}, timeout=15)
    assert r.status_code == 200
    words = {w["text"].lower().strip(",.:;'") for w in r.json()["words"]}
    # Expect at least some of: little, butter, better, water, getting
    expected = {"little", "butter", "better", "water", "getting"}
    assert expected & words, f"none of {expected} found in {words}"


# --- TTS --------------------------------------------------------------------
def test_tts_empty_word(session):
    r = session.post(f"{API}/tts", json={"word": ""}, timeout=15)
    assert r.status_code == 400


def test_tts_proxies_elevenlabs(session):
    """Free-tier ElevenLabs is expected to 401 from cloud IPs.
    The endpoint should return 502 with the upstream error in detail.
    OR succeed with audio_b64 if a valid paid key is provided."""
    r = session.post(f"{API}/tts", json={"word": "butter"}, timeout=60)
    assert r.status_code in (200, 502), f"Unexpected status {r.status_code}: {r.text}"
    if r.status_code == 200:
        body = r.json()
        assert body.get("audio_b64")
        assert body["word"] == "butter"
    else:
        # 502 with detail message
        detail = r.json().get("detail", "")
        assert "TTS failed" in detail or "TTS" in detail


# --- Delete -----------------------------------------------------------------
def test_delete_scene_flow(session, sample_pdf_bytes):
    files = {"file": ("delete_me.pdf", sample_pdf_bytes, "application/pdf")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=120)
    assert r.status_code == 200
    sid = r.json()["id"]
    r = session.delete(f"{API}/scenes/{sid}", timeout=15)
    assert r.status_code == 200
    assert r.json().get("ok") is True
    r = session.get(f"{API}/scenes/{sid}", timeout=10)
    assert r.status_code == 404
    # second delete -> 404
    r = session.delete(f"{API}/scenes/{sid}", timeout=10)
    assert r.status_code == 404
