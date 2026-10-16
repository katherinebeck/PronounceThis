# Accent guard admin API + /api/pronounce forced GA IPA (iteration 35)
import os
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


def _jwt():
    cmd = "cd /app/backend && set -a && . ./.env && set +a && python3 -c \"from auth import _issue_jwt; print(_issue_jwt('katherine@katherinebeck.com'))\""
    return subprocess.check_output(["bash", "-c", cmd]).decode().strip().splitlines()[-1]


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    s.cookies.set("accent_session", _jwt())
    return s


def _words(admin):
    r = admin.get(f"{BASE_URL}/api/admin/accent-guard")
    assert r.status_code == 200
    return {e["word"]: e["ipa"] for e in r.json()["entries"]}


class TestAccentGuard:
    def test_requires_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/accent-guard")
        assert r.status_code in (401, 403)

    def test_list_seeded(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/accent-guard")
        data = r.json()
        assert len(data["entries"]) >= 70
        assert data["default_count"] >= 70
        w = {e["word"]: e["ipa"] for e in data["entries"]}
        assert w["strewth"] == "stɹuθ"
        assert all(e["ipa"] for e in data["entries"])
        assert [e["word"] for e in data["entries"]] == sorted(w)

    def test_add_with_ipa_and_delete(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/accent-guard", json={"word": "  Test_Zork  Blah ", "ipa": "zɔɹk blɑ"})
        assert r.status_code == 200
        assert r.json()["entry"] == {"word": "test_zork blah", "ipa": "zɔɹk blɑ"}
        assert _words(admin)["test_zork blah"] == "zɔɹk blɑ"
        d = admin.post(f"{BASE_URL}/api/admin/accent-guard/delete", json={"word": "test_zork blah"})
        assert d.status_code == 200
        assert "test_zork blah" not in _words(admin)

    def test_add_unknown_without_ipa_400(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/accent-guard", json={"word": "zzqxtest"})
        assert r.status_code == 400
        assert "isn't in the dictionary" in r.json()["detail"]
        assert "zzqxtest" not in _words(admin)

    def test_add_empty_word_400(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/accent-guard", json={"word": "   ", "ipa": "x"})
        assert r.status_code == 400

    def test_add_cmu_word_without_ipa(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/accent-guard", json={"word": "kangaroo"})
        assert r.status_code == 200
        ipa = r.json()["entry"]["ipa"]
        assert isinstance(ipa, str) and len(ipa) > 3
        assert _words(admin)["kangaroo"] == ipa
        admin.post(f"{BASE_URL}/api/admin/accent-guard/delete", json={"word": "kangaroo"})
        assert "kangaroo" not in _words(admin)

    def test_pronounce_strewth_uses_guard(self, admin):
        r = admin.get(f"{BASE_URL}/api/pronounce", params={"word": "strewth"})
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "stɹuθ" in str(data.get("ipa")), data.get("ipa")
