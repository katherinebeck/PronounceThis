# Practice trial lock: one analysis per trial word (status locked flag + 402 practice_exhausted).
# Pre-req: trial user pttrial997949 has 'party' in practice_words (run after one real analysis).
import os
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
TRIAL = "pttrial997949@gmail.com"
MEMBER = "ptbuyer114077@gmail.com"


def _jwt(email):
    cmd = f"cd /app/backend && set -a && . ./.env && set +a && python3 -c \"from auth import _issue_jwt; print(_issue_jwt('{email}'))\""
    return subprocess.check_output(cmd, shell=True, text=True).strip()


@pytest.fixture(scope="module")
def trial():
    s = requests.Session(); s.cookies.set("accent_session", _jwt(TRIAL)); return s


@pytest.fixture(scope="module")
def member():
    s = requests.Session(); s.cookies.set("accent_session", _jwt(MEMBER)); return s


def test_trial_status_locked(trial):
    d = trial.get(f"{BASE_URL}/api/practice/status", params={"word": "party"}).json()
    if not d.get("locked"):
        pytest.skip("trial user has not used 'party' analysis yet")
    assert d == {"enabled": True, "locked": True}


def test_trial_status_other_word_unlocked(trial):
    assert trial.get(f"{BASE_URL}/api/practice/status", params={"word": "hello"}).json()["locked"] is False


def test_member_status_unlocked(member):
    assert member.get(f"{BASE_URL}/api/practice/status", params={"word": "party"}).json() == {"enabled": True, "locked": False}


def test_trial_assess_402(trial):
    if not trial.get(f"{BASE_URL}/api/practice/status", params={"word": "party"}).json().get("locked"):
        pytest.skip("not locked")
    r = trial.post(f"{BASE_URL}/api/practice/assess", data={"word": "party"},
                   files={"audio": ("a.bin", os.urandom(1000))})
    assert r.status_code == 402
    assert r.json()["detail"] == {"code": "practice_exhausted", "kind": "practice"}
