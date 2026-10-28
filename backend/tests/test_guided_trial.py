# Guided 3-step trial: word limit 1, sample scene access, locks, admin sample-scene API, legacy regression
import os
import subprocess
import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


BASE_URL = _env("/app/frontend/.env", "REACT_APP_BACKEND_URL").rstrip("/")
SUPA_URL = _env("/app/frontend/.env", "REACT_APP_SUPABASE_URL")
ANON = _env("/app/frontend/.env", "REACT_APP_SUPABASE_ANON_KEY")
MONGO_URL = _env("/app/backend/.env", "MONGO_URL")
DB_NAME = _env("/app/backend/.env", "DB_NAME")
TRIAL_EMAIL = "pttrial997949@gmail.com"
TRIAL_PW = "Trial2026pass"
SAMPLE_ID = "48727781-390e-4af9-af3f-49d5282ad610"

db = MongoClient(MONGO_URL)[DB_NAME]


def reset_trial():
    db.users.update_one({"email": TRIAL_EMAIL},
                        {"$set": {"guided_trial": True, "trial_word_used": 0, "trial_words": []},
                         "$unset": {"trial_exhausted_at": "", "sample_scene_explored_at": ""}})
    db.trial_devices.delete_many({"emails": TRIAL_EMAIL})


def supa_token(email, pw):
    r = requests.post(f"{SUPA_URL}/auth/v1/token?grant_type=password",
                      headers={"apikey": ANON}, json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def trial():
    reset_trial()
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {supa_token(TRIAL_EMAIL, TRIAL_PW)}"
    yield s
    reset_trial()


@pytest.fixture(scope="module")
def admin():
    jwt = subprocess.check_output(
        "cd /app/backend && set -a && . ./.env && set +a && python3 -c \"from auth import _issue_jwt; print(_issue_jwt('katherine@katherinebeck.com'))\"",
        shell=True, executable="/bin/bash").decode().strip().splitlines()[-1]
    s = requests.Session()
    s.cookies.set("accent_session", jwt)
    return s


class TestGuided:
    def test_01_me(self, trial):
        d = trial.get(f"{BASE_URL}/api/auth/me").json()
        assert d["guided_trial"] is True
        assert d["trial_word_limit"] == 1
        assert d["trial_scene_limit"] == 0
        assert d["sample_scene_explored"] is False

    def test_02_word_limit(self, trial):
        assert trial.get(f"{BASE_URL}/api/pronounce", params={"word": "water"}).status_code == 200
        r = trial.get(f"{BASE_URL}/api/pronounce", params={"word": "bottle"})
        assert r.status_code == 402
        assert "trial_exhausted" in r.text and "word" in r.text
        assert trial.get(f"{BASE_URL}/api/pronounce", params={"word": "water"}).status_code == 200

    def test_03_sample_scene(self, trial):
        r = trial.get(f"{BASE_URL}/api/scenes/sample")
        assert r.status_code == 200
        d = r.json()
        assert d["is_sample"] is True and d["id"] == SAMPLE_ID and len(d["turns"]) > 0
        assert trial.get(f"{BASE_URL}/api/scenes/{SAMPLE_ID}").status_code == 200

    def test_04_tts_bypass(self, trial):
        r = trial.post(f"{BASE_URL}/api/tts", json={"word": "house", "scene_id": SAMPLE_ID}, timeout=60)
        assert r.status_code == 200, r.text
        r = trial.post(f"{BASE_URL}/api/tts", json={"word": "garden"}, timeout=60)
        assert r.status_code == 402

    def test_05_turn_tts_marks_explored(self, trial):
        r = trial.post(f"{BASE_URL}/api/scenes/{SAMPLE_ID}/turns/0/tts", timeout=90)
        assert r.status_code == 200, r.text
        assert trial.get(f"{BASE_URL}/api/auth/me").json()["sample_scene_explored"] is True

    def test_06_locks(self, trial):
        r = trial.get(f"{BASE_URL}/api/scenes/{SAMPLE_ID}/download-lines", params={"character": "FLOYD"})
        assert r.status_code == 402
        assert trial.delete(f"{BASE_URL}/api/scenes/{SAMPLE_ID}").status_code == 403
        r = trial.post(f"{BASE_URL}/api/scenes/upload",
                       files={"file": ("x.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
        assert r.status_code == 402, r.text
        assert "scene" in r.text
        # sample still exists
        assert db.scenes.find_one({"id": SAMPLE_ID})["is_sample"] is True


class TestAdminSample:
    def test_get(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/sample-scene")
        assert r.status_code == 200, r.text
        d = r.json()
        print(list(d.keys()))
        assert d["current"]["id"] == SAMPLE_ID

    def test_set_clear_reset(self, admin):
        lst = admin.get(f"{BASE_URL}/api/admin/sample-scene").json()
        scenes = lst.get("scenes") or []
        other = next((s for s in scenes if s["id"] != SAMPLE_ID), None)
        if other:
            assert admin.post(f"{BASE_URL}/api/admin/sample-scene", json={"scene_id": other["id"]}).status_code == 200
            assert db.scenes.count_documents({"is_sample": True}) == 1
            assert db.scenes.find_one({"is_sample": True})["id"] == other["id"]
        assert admin.delete(f"{BASE_URL}/api/admin/sample-scene").status_code == 200
        assert db.scenes.count_documents({"is_sample": True}) == 0
        assert admin.get(f"{BASE_URL}/api/admin/sample-scene").json()["current"] in (None, {})
        assert admin.post(f"{BASE_URL}/api/admin/sample-scene", json={"scene_id": SAMPLE_ID}).status_code == 200
        assert db.scenes.count_documents({"is_sample": True}) == 1
        assert db.scenes.find_one({"is_sample": True})["id"] == SAMPLE_ID

    def test_bad_id(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/sample-scene", json={"scene_id": "nope"})
        assert r.status_code in (400, 404)
        assert db.scenes.find_one({"is_sample": True})["id"] == SAMPLE_ID

    def test_non_admin_forbidden(self, trial):
        assert trial.get(f"{BASE_URL}/api/admin/sample-scene").status_code in (401, 403)


class TestLegacy:
    def test_legacy_limits(self, trial):
        db.users.update_one({"email": TRIAL_EMAIL}, {"$unset": {"guided_trial": ""}})
        try:
            d = trial.get(f"{BASE_URL}/api/auth/me").json()
            assert d["guided_trial"] is False
            assert d["trial_word_limit"] == 2 and d["trial_scene_limit"] == 1
        finally:
            db.users.update_one({"email": TRIAL_EMAIL}, {"$set": {"guided_trial": True}})
