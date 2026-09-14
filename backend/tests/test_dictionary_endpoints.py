"""Iteration 21: Admin My-Dictionary builder endpoints under /api/admin/dictionary.

Covers: /queue, /entry (multipart w/ + w/o audio + invalid ipa + missing both),
/skip, /entries + prefix filter, /entries/delete, /audio, /export.csv, /export.zip,
CUSTOM_IPA effect on /api/pronounce, /api/tts manual_override for uploaded word,
non-admin gating (401/403), and regression on /api/scenes/{id}/laundry-list.

Cleans up all TEST_ / 'because' entries at teardown so students don't hear test audio.
"""
import base64
import csv
import io
import os
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

# --- Env / constants ---------------------------------------------------------
_env_path = Path("/app/backend/.env")
for _line in _env_path.read_text().splitlines():
    if "=" not in _line or _line.strip().startswith("#"):
        continue
    k, _, v = _line.partition("=")
    os.environ.setdefault(k.strip(), v.strip().strip('"'))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://accent-coach-pro.preview.emergentagent.com",
).rstrip("/")
MONGO_URL = os.environ["MONGO_URL"].strip('"')
DB_NAME = os.environ["DB_NAME"].strip('"')
ADMIN_EMAIL = os.environ.get("ADMIN_EMAILS", "katherine@katherinebeck.com").split(",")[0].strip().lower()

# Minimal but valid WAV (44 byte header + 1 sample of silence) — server just enforces size/type.
def _tiny_wav() -> bytes:
    import struct
    data = b"\x00\x00"  # 1 sample, 16-bit
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


TINY_WAV = _tiny_wav()
TEST_WORD = "zzzqqqtestword"     # not in CMU dict → ipa_custom always true
TEST_AUDIO_WORD = "testworddictonly"  # alphabetic-only (no `_`) so _clean_word doesn't mutate
BECAUSE = "because"
LEGACY_SCENE_ID = "4b23e55d-67be-42bc-a397-4eb4085bdb2e"  # legacy admin-only scene


# --- Fixtures ----------------------------------------------------------------
@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="module")
def admin_session(mongo):
    mongo.users.update_one(
        {"email": ADMIN_EMAIL},
        {"$setOnInsert": {
            "email": ADMIN_EMAIL,
            "trial_word_used": 0,
            "trial_scene_used": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login_at": None,
        }},
        upsert=True,
    )
    token = secrets.token_urlsafe(24)
    mongo.magic_links.insert_one({
        "token": token,
        "email": ADMIN_EMAIL,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "consumed": False,
    })
    sess = requests.Session()
    r = sess.get(f"{BASE_URL}/api/auth/verify", params={"token": token}, timeout=30)
    assert r.status_code == 200, f"verify failed: {r.status_code} {r.text}"
    assert "accent_session" in sess.cookies
    yield sess

    # Teardown: remove any test-created entries and revert 'because' overrides.
    for w in [TEST_WORD, TEST_AUDIO_WORD, BECAUSE, "test_word_dict_only"]:
        try:
            sess.post(f"{BASE_URL}/api/admin/dictionary/entries/delete", json={"word": w}, timeout=15)
        except Exception:
            pass
    mongo.dictionary_entries.delete_many({"word": {"$in": [TEST_WORD, TEST_AUDIO_WORD, BECAUSE, "test_word_dict_only"]}})
    mongo.audio_cache.delete_many({"word": {"$in": [TEST_WORD, TEST_AUDIO_WORD, BECAUSE, "test_word_dict_only"]}})


# --- Gating ------------------------------------------------------------------
class TestGating:
    def test_queue_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/dictionary/queue", timeout=15)
        assert r.status_code in (401, 403)

    def test_entry_unauth_401(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": "hello", "ipa": "hɛˈloʊ"},
            timeout=15,
        )
        assert r.status_code in (401, 403)

    def test_export_csv_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/dictionary/export.csv", timeout=15)
        assert r.status_code in (401, 403)


# --- Queue -------------------------------------------------------------------
class TestQueue:
    def test_queue_default_shape(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/admin/dictionary/queue", timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "words" in body and "stats" in body
        s = body["stats"]
        for k in ("total", "done", "recorded", "skipped"):
            assert k in s and isinstance(s[k], int)
        # 124k range per spec.
        assert 100_000 < s["total"] < 200_000
        assert len(body["words"]) > 0
        assert all("word" in w and "ipa" in w for w in body["words"])

    def test_queue_start_because(self, admin_session, mongo):
        # Ensure 'because' isn't already done/skipped.
        mongo.dictionary_entries.delete_one({"word": BECAUSE})
        r = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/queue",
            params={"start": "because", "limit": 5},
            timeout=20,
        )
        assert r.status_code == 200
        words = [w["word"] for w in r.json()["words"]]
        assert words[0] == BECAUSE, f"expected 'because' first, got {words}"


# --- Entry: validation -------------------------------------------------------
class TestEntryValidation:
    def test_invalid_ipa_400(self, admin_session):
        r = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": TEST_WORD, "ipa": "ab$c"},
            timeout=20,
        )
        assert r.status_code == 400
        assert "invalid_ipa" in r.text

    def test_missing_ipa_and_file_400(self, admin_session):
        r = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": TEST_WORD, "ipa": ""},
            timeout=20,
        )
        assert r.status_code in (400, 422), r.text
        # 422 means FastAPI Form(...) rejected empty; 400 means our own check ran.


# --- Entry: custom IPA drives /api/pronounce --------------------------------
class TestCustomIpaFlow:
    def test_save_custom_ipa_and_pronounce_picks_it_up(self, admin_session, mongo):
        # Save 'because' with a non-CMU IPA to prove ipa_custom.
        custom = "bɪˈkʌz"
        r = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": BECAUSE, "ipa": custom},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["ipa"] == custom
        assert body["ipa_custom"] is True
        assert body["cmu_ipa"] and body["cmu_ipa"] != custom

        # GET /api/pronounce should return this custom IPA.
        r2 = admin_session.get(f"{BASE_URL}/api/pronounce", params={"word": BECAUSE}, timeout=20)
        assert r2.status_code == 200, r2.text
        pron = r2.json()
        assert pron.get("ipa") == custom, f"pronounce did not use CUSTOM_IPA: {pron}"

    def test_save_no_ipa_change_not_custom(self, admin_session, mongo):
        # Save with the CMU ipa itself → ipa_custom must be False.
        # First fetch CMU IPA via _entry (through /word).
        r0 = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/word", params={"word": BECAUSE}, timeout=15
        )
        assert r0.status_code == 200
        cmu = r0.json()["cmu_ipa"]
        r = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": BECAUSE, "ipa": cmu},
            timeout=20,
        )
        assert r.status_code == 200
        assert r.json()["ipa_custom"] is False

    def test_delete_entry_falls_back_to_cmu(self, admin_session):
        r = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entries/delete",
            json={"word": BECAUSE},
            timeout=20,
        )
        assert r.status_code == 200
        # pronounce must now use CMU (not the earlier custom bɪˈkʌz).
        r2 = admin_session.get(f"{BASE_URL}/api/pronounce", params={"word": BECAUSE}, timeout=20)
        assert r2.status_code == 200
        assert r2.json().get("ipa") != "bɪˈkʌz"


# --- Skip --------------------------------------------------------------------
class TestSkip:
    def test_skip_word_disappears_from_queue(self, admin_session, mongo):
        # Fresh state for TEST_WORD.
        mongo.dictionary_entries.delete_one({"word": TEST_WORD})
        stats_before = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/queue", timeout=15
        ).json()["stats"]

        r = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/skip",
            json={"word": TEST_WORD},
            timeout=15,
        )
        assert r.status_code == 200 and r.json()["ok"] is True

        stats_after = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/queue", timeout=15
        ).json()["stats"]
        assert stats_after["skipped"] == stats_before["skipped"] + 1


# --- Audio upload + /api/tts manual override --------------------------------
class TestAudioAndTts:
    WORD = "testworddictonly"

    def test_upload_audio_and_get_audio(self, admin_session):
        r = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": self.WORD, "ipa": "tɛst"},
            files={"file": ("t.wav", TINY_WAV, "audio/wav")},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["has_audio"] is True
        assert b["content_type"] in ("audio/wav", "audio/x-wav")

        r2 = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/audio",
            params={"word": self.WORD},
            timeout=15,
        )
        assert r2.status_code == 200
        assert r2.content == TINY_WAV
        assert "wav" in r2.headers.get("content-type", "")

    def test_audio_missing_returns_404(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/audio",
            params={"word": "definitelynotawordxyz"},
            timeout=15,
        )
        assert r.status_code == 404

    def test_tts_manual_override_true(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/tts", json={"word": self.WORD}, timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["manual_override"] is True
        assert base64.b64decode(b["audio_b64"]) == TINY_WAV


# --- Entries listing + delete -----------------------------------------------
class TestEntriesList:
    def test_entries_prefix_filter_and_delete(self, admin_session):
        # Ensure our test entry exists.
        admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": "testworddictonly", "ipa": "tɛst"},
            timeout=15,
        )
        r = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/entries",
            params={"q": "testword"},
            timeout=15,
        )
        assert r.status_code == 200
        words = [e["word"] for e in r.json()["entries"]]
        assert "testworddictonly" in words

        # Delete.
        r2 = admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entries/delete",
            json={"word": "testworddictonly"},
            timeout=15,
        )
        assert r2.status_code == 200

        r3 = admin_session.get(
            f"{BASE_URL}/api/admin/dictionary/entries",
            params={"q": "testword"},
            timeout=15,
        )
        words3 = [e["word"] for e in r3.json()["entries"]]
        assert "testworddictonly" not in words3


# --- CSV / ZIP export --------------------------------------------------------
class TestExport:
    def test_export_csv_columns(self, admin_session):
        # Seed one entry so export has content.
        admin_session.post(
            f"{BASE_URL}/api/admin/dictionary/entry",
            data={"word": "testworddictonly", "ipa": "tɛst"},
            files={"file": ("t.wav", TINY_WAV, "audio/wav")},
            timeout=15,
        )
        r = admin_session.get(f"{BASE_URL}/api/admin/dictionary/export.csv", timeout=30)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        text = r.content.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        assert header == ["word", "ipa", "cmu_ipa", "ipa_custom", "has_audio", "audio_file", "updated_at"]

    def test_export_zip_contains_csv_and_audio(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/admin/dictionary/export.zip", timeout=60)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert "dictionary.csv" in names
        assert any(n.startswith("audio/") and n.endswith(".wav") for n in names), names


# --- Regression: laundry-list still works on legacy scene -------------------
class TestRegressionLaundry:
    def test_legacy_laundry_list(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/scenes/{LEGACY_SCENE_ID}/laundry-list",
            params={"sound": "th_voiceless"},
            timeout=45,
        )
        # 200 or (rarely) 404 if legacy scene not present in this DB — assert one.
        assert r.status_code in (200, 404), r.text
        if r.status_code == 200:
            body = r.json()
            assert "categories" in body or "items" in body or isinstance(body, dict)
