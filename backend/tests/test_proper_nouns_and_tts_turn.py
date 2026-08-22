"""Backend tests for:
  1. `is_proper_noun` field on WordToken after upload/get/reparse.
  2. Legacy-scene migration: `_ensure_dialogue_only` only re-runs when both
     dialogue_only=True AND proper_nouns key exist; simulate legacy by
     directly editing the Mongo doc to drop proper_nouns.
  3. `POST /scenes/{id}/turns/{i}/tts` uses persisted doc['turns'][i]['text']
     (not regex extract_turns on raw_text). Verified on the Little House seed
     scene: turn 0 and last turn return audio + doc['turns'][i].speaker
     matching the response.speaker; out-of-range → 404.
  4. Turn-TTS cache invalidation after reparse.
"""
import io
import os
import time
import pytest
import requests
from reportlab.pdfgen import canvas
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SEED_SCENE_ID = "4b23e55d-67be-42bc-a397-4eb4085bdb2e"


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


def _upload(session, lines, title="pn"):
    files = {"file": (f"{title}.pdf", _pdf(lines), "application/pdf")}
    r = session.post(f"{API}/scenes/upload", files=files, timeout=180)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def session():
    return requests.Session()


# =========================================================================
# 1. Proper-noun tagging on upload
# =========================================================================
@pytest.fixture(scope="module")
def pn_scene(session):
    lines = [
        "ELIZA: I met Miss Whitmore in Boston.",
        "ELIZA: Mary Jones was there too.",
    ]
    data = _upload(session, lines, "pn-basic")
    yield data
    session.delete(f"{API}/scenes/{data['id']}")


def _word_tokens(scene):
    return [t for t in scene["tokens"] if t.get("is_word")]


def _flagged(scene):
    return {t["text"] for t in _word_tokens(scene) if t.get("is_proper_noun")}


def _unflagged(scene):
    return {t["text"] for t in _word_tokens(scene) if not t.get("is_proper_noun")}


def test_upload_tokens_have_is_proper_noun_field(pn_scene):
    for t in _word_tokens(pn_scene):
        assert "is_proper_noun" in t, f"missing is_proper_noun on {t}"
        assert isinstance(t["is_proper_noun"], bool)


def test_positive_proper_nouns_detected(pn_scene):
    flagged = _flagged(pn_scene)
    # Positive-only assertion per problem statement.
    expected = {"Miss", "Whitmore", "Boston", "Mary", "Jones"}
    missing = expected - flagged
    assert not missing, (
        f"expected these to be flagged as proper nouns: {missing}; "
        f"actually flagged: {flagged}"
    )


def test_common_words_not_flagged(pn_scene):
    unflagged_lower = {w.lower().strip(",.") for w in _unflagged(pn_scene)}
    # Common words MUST NOT be flagged. "I" is len<2 so skipped by design.
    for common in ("in", "was", "there", "met", "too"):
        # word may not be present at all if LLM rephrased; that's fine.
        # But if present, it must be unflagged.
        flagged_lower = {w.lower().strip(",.") for w in _flagged(pn_scene)}
        assert common not in flagged_lower, (
            f"common word '{common}' incorrectly flagged as proper noun"
        )


def test_scene_persists_proper_nouns_and_get_returns_flags(session, pn_scene):
    r = session.get(f"{API}/scenes/{pn_scene['id']}", timeout=30)
    assert r.status_code == 200
    data = r.json()
    flagged = {t["text"] for t in data["tokens"]
               if t.get("is_word") and t.get("is_proper_noun")}
    # Same flags as the upload response.
    upload_flagged = _flagged(pn_scene)
    assert flagged == upload_flagged, (
        f"GET flags {flagged} != upload flags {upload_flagged}"
    )


# ---------- possessive: Mary's ---------------------------------------------
@pytest.fixture(scope="module")
def possessive_scene(session):
    lines = ["ELIZA: That is Mary's book."]
    data = _upload(session, lines, "pn-possessive")
    yield data
    session.delete(f"{API}/scenes/{data['id']}")


def test_possessive_proper_noun_flagged(possessive_scene):
    marys = [t for t in _word_tokens(possessive_scene)
             if t["text"].lower().startswith("mary")]
    assert marys, f"no 'Mary's' token in {possessive_scene['tokens']}"
    # At least one 'Mary'-rooted token must be flagged.
    assert any(t.get("is_proper_noun") for t in marys), (
        f"possessive 'Mary's' not flagged: {marys}"
    )


# =========================================================================
# 2. Legacy-scene migration guard
# =========================================================================
def _mongo_db():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = MongoClient(mongo_url)
    return client, client[db_name]


@pytest.fixture(scope="module")
def legacy_sim_scene(session):
    """Upload a fresh scene, then simulate the legacy shape by unsetting the
    `proper_nouns` key + flipping `dialogue_only` to false directly in mongo.
    """
    lines = [
        "ELIZA: I saw Mary in Boston.",
        "MARK: Miss Whitmore lives there.",
    ]
    data = _upload(session, lines, "pn-legacy")
    sid = data["id"]

    client, db = _mongo_db()
    db.scenes.update_one(
        {"id": sid},
        {"$unset": {"proper_nouns": "", "dialogue_only": ""}},
    )
    client.close()

    yield sid
    session.delete(f"{API}/scenes/{sid}")


def test_legacy_scene_migrates_on_get(session, legacy_sim_scene):
    sid = legacy_sim_scene
    t0 = time.time()
    r = session.get(f"{API}/scenes/{sid}", timeout=180)
    dt1 = time.time() - t0
    assert r.status_code == 200, r.text
    data = r.json()
    # After migration tokens carry is_proper_noun booleans.
    for t in data["tokens"]:
        if t.get("is_word"):
            assert isinstance(t.get("is_proper_noun"), bool)

    first_flags = {t["text"] for t in data["tokens"]
                   if t.get("is_word") and t.get("is_proper_noun")}
    # Expect at least some of the known proper nouns.
    assert first_flags & {"Mary", "Boston", "Miss", "Whitmore"}, (
        f"no known proper nouns flagged after migration: {first_flags}"
    )

    # Second GET should be fast (< 2s) — migration persisted.
    t0 = time.time()
    r2 = session.get(f"{API}/scenes/{sid}", timeout=15)
    dt2 = time.time() - t0
    assert r2.status_code == 200
    assert dt2 < 2.0, f"second GET too slow ({dt2:.2f}s vs first {dt1:.2f}s)"

    second_flags = {t["text"] for t in r2.json()["tokens"]
                    if t.get("is_word") and t.get("is_proper_noun")}
    assert second_flags == first_flags, (
        f"flags changed between GETs: {first_flags} vs {second_flags}"
    )


# =========================================================================
# 3. Reparse re-detects proper nouns even for migrated scenes
# =========================================================================
def test_reparse_re_detects_proper_nouns(session, pn_scene):
    # pn_scene is already dialogue_only + has proper_nouns (guard would skip
    # re-migration). Reparse must force re-run.
    r = session.post(f"{API}/scenes/{pn_scene['id']}/reparse", timeout=180)
    assert r.status_code == 200, r.text
    data = r.json()
    flagged = {t["text"] for t in data["tokens"]
               if t.get("is_word") and t.get("is_proper_noun")}
    assert flagged & {"Miss", "Whitmore", "Boston", "Mary", "Jones"}, (
        f"reparse dropped proper-noun tags: {flagged}"
    )


# =========================================================================
# 4. tts_turn uses persisted doc['turns'] — seed Little House scene
# =========================================================================
def test_tts_turn_uses_persisted_turns_on_seed(session):
    """Verify audio matches doc['turns'][i]['speaker'] for turn 0 and last;
    turn 7 → 404. Indirect check that endpoint reads doc['turns'] not the
    regex extract_turns(raw_text)."""
    g = session.get(f"{API}/scenes/{SEED_SCENE_ID}", timeout=60)
    if g.status_code == 404:
        pytest.skip("Little House seed scene not present")
    scene = g.json()
    turns = scene["turns"]
    assert len(turns) == 7, f"expected 7 dialogue turns, got {len(turns)}"

    # Turn 0
    r0 = session.post(
        f"{API}/scenes/{SEED_SCENE_ID}/turns/0/tts", timeout=120
    )
    assert r0.status_code in (200, 502), r0.text
    if r0.status_code == 502:
        pytest.skip(f"ElevenLabs upstream failure: {r0.json().get('detail')}")
    body0 = r0.json()
    assert body0["speaker"] == turns[0]["speaker"], (
        f"turn-0 speaker mismatch: response={body0['speaker']} "
        f"doc={turns[0]['speaker']}"
    )
    assert isinstance(body0["audio_b64"], str) and len(body0["audio_b64"]) > 100

    # Last turn (index 6)
    r6 = session.post(
        f"{API}/scenes/{SEED_SCENE_ID}/turns/6/tts", timeout=120
    )
    assert r6.status_code in (200, 502)
    if r6.status_code == 502:
        pytest.skip(f"ElevenLabs upstream failure: {r6.json().get('detail')}")
    body6 = r6.json()
    assert body6["turn_index"] == 6
    assert body6["speaker"] == turns[6]["speaker"], (
        f"turn-6 speaker mismatch: response={body6['speaker']} "
        f"doc={turns[6]['speaker']}"
    )

    # Turn 7 out of range → 404
    r7 = session.post(
        f"{API}/scenes/{SEED_SCENE_ID}/turns/7/tts", timeout=15
    )
    assert r7.status_code == 404, r7.text


# =========================================================================
# 5. Cache invalidation after reparse
# =========================================================================
@pytest.fixture(scope="module")
def cache_scene(session):
    lines = [
        "ELIZA: I want a little butter on my bread.",
        "MARK: Better hurry.",
    ]
    data = _upload(session, lines, "pn-cache")
    yield data
    session.delete(f"{API}/scenes/{data['id']}")


def test_tts_cache_invalidated_after_reparse(session, cache_scene):
    sid = cache_scene["id"]

    # First call — may be cached=False (or True if a previous run left it).
    r1 = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=120)
    assert r1.status_code in (200, 502), r1.text
    if r1.status_code == 502:
        pytest.skip(f"ElevenLabs upstream failure: {r1.json().get('detail')}")
    body1 = r1.json()
    assert isinstance(body1["audio_b64"], str) and len(body1["audio_b64"]) > 100

    # Second call — must now be cached.
    r2 = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=30)
    assert r2.status_code == 200
    assert r2.json()["cached"] is True, "expected second call to be cached"

    # Reparse invalidates the cache.
    rp = session.post(f"{API}/scenes/{sid}/reparse", timeout=180)
    assert rp.status_code == 200, rp.text

    # Third call after reparse — must NOT be cached anymore.
    r3 = session.post(f"{API}/scenes/{sid}/turns/0/tts", timeout=120)
    assert r3.status_code in (200, 502)
    if r3.status_code == 502:
        pytest.skip(f"ElevenLabs upstream failure: {r3.json().get('detail')}")
    body3 = r3.json()
    assert body3["cached"] is False, (
        "expected cache to be invalidated after reparse, got cached=True"
    )
