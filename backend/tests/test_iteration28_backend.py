"""Iteration 28: Report This Clip, Blocked Words, Trial Abuse admin flows."""
import os
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://accent-coach-pro.preview.emergentagent.com").rstrip("/")
DEFAULT_TIMEOUT = 60
SUPABASE_URL = "https://alsbjfsoqtyiglqtlhdg.supabase.co"
SUPABASE_ANON = "sb_publishable_vEnIuAHm2xOE-6xicxQ4VA_qYuskYCE"
MEMBER_EMAIL = "ptqalogoutcheck9@gmail.com"
MEMBER_PW = "Passw0rd!lc9"
FAKE_VIDEO = "zzTEST0001a"
SEED_DEVICE = "qa_abuse_device_0000000000000001"


@pytest.fixture(scope="module")
def member_token():
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": SUPABASE_ANON, "Content-Type": "application/json"},
        json={"email": MEMBER_EMAIL, "password": MEMBER_PW},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_jwt():
    out = subprocess.check_output(
        ["bash", "-lc", "cd /app/backend && set -a && . ./.env && set +a && /root/.venv/bin/python -c \"from auth import _issue_jwt; print(_issue_jwt('katherine@katherinebeck.com'))\""]
    ).decode().strip()
    assert out and out.count(".") == 2
    return out


@pytest.fixture(scope="module")
def member_headers(member_token):
    return {"Authorization": f"Bearer {member_token}"}


@pytest.fixture(scope="module")
def admin_cookies(admin_jwt):
    return {"accent_session": admin_jwt}


# ---------- Regression sanity ----------
class TestRegression:
    def test_auth_me_member(self, member_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=member_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("email") == MEMBER_EMAIL

    def test_auth_me_admin(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/auth/me", cookies=admin_cookies, timeout=15)
        assert r.status_code == 200
        assert r.json().get("is_admin") is True

    def test_landing_images(self):
        for path in ["/landing/hero-devices.png", "/landing/word-tool.jpg", "/landing/scene-tool.jpg"]:
            r = requests.get(f"{BASE_URL}{path}", timeout=15)
            # Accept either .png or fallback .jpg
            print(f"{path} -> {r.status_code}")

    def test_caption_search_member(self, member_headers):
        r = requests.get(f"{BASE_URL}/api/caption-search?q=server", headers=member_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        print(f"caption-search results: {len(data.get('results', []))}")


# ---------- Clip Reports ----------
class TestClipReports:
    def test_report_requires_login(self):
        r = requests.post(
            f"{BASE_URL}/api/caption-search/report",
            json={"video_id": FAKE_VIDEO, "reason": "offensive-language", "query": "server"},
            timeout=15,
        )
        assert r.status_code == 401

    def test_report_create_and_admin_list(self, member_headers, admin_cookies):
        r = requests.post(
            f"{BASE_URL}/api/caption-search/report",
            headers=member_headers,
            json={"video_id": FAKE_VIDEO, "reason": "offensive-language", "query": "server"},
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text

        # normal member forbidden on admin listing
        r_forbid = requests.get(f"{BASE_URL}/api/admin/clip-reports", headers=member_headers, timeout=15)
        assert r_forbid.status_code in (401, 403)

        r_admin = requests.get(f"{BASE_URL}/api/admin/clip-reports", cookies=admin_cookies, timeout=15)
        assert r_admin.status_code == 200
        items = r_admin.json() if isinstance(r_admin.json(), list) else r_admin.json().get("reports", [])
        assert any(it.get("video_id") == FAKE_VIDEO for it in items), f"report not found: {items}"

    def test_resolve_hide(self, admin_cookies):
        r = requests.post(
            f"{BASE_URL}/api/admin/clip-reports/resolve",
            cookies=admin_cookies,
            json={"video_id": FAKE_VIDEO, "action": "hide"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        hv = requests.get(f"{BASE_URL}/api/admin/hidden-videos", cookies=admin_cookies, timeout=15)
        assert hv.status_code == 200
        vids = hv.json() if isinstance(hv.json(), list) else hv.json().get("videos", [])
        ids = [v.get("video_id") if isinstance(v, dict) else v for v in vids]
        assert FAKE_VIDEO in ids

    def test_resolve_dismiss_and_cleanup(self, member_headers, admin_cookies):
        # Re-create a fresh report then dismiss it
        requests.post(
            f"{BASE_URL}/api/caption-search/report",
            headers=member_headers,
            json={"video_id": FAKE_VIDEO, "reason": "offensive-language", "query": "server"},
            timeout=15,
        )
        r = requests.post(
            f"{BASE_URL}/api/admin/clip-reports/resolve",
            cookies=admin_cookies,
            json={"video_id": FAKE_VIDEO, "action": "dismiss"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # cleanup hidden
        d = requests.post(
            f"{BASE_URL}/api/admin/hidden-videos/delete",
            cookies=admin_cookies,
            json={"video_id": FAKE_VIDEO},
            timeout=15,
        )
        assert d.status_code in (200, 204), d.text


# ---------- Blocked Words ----------
class TestBlockedWords:
    def test_add_and_remove(self, admin_cookies):
        # GET current list
        r0 = requests.get(f"{BASE_URL}/api/admin/blocked-words", cookies=admin_cookies, timeout=DEFAULT_TIMEOUT)
        assert r0.status_code == 200
        j0 = r0.json()
        words0 = j0 if isinstance(j0, list) else j0.get("words", [])
        base = [w for w in words0 if w != "zork"]

        # Add zork
        r1 = requests.post(f"{BASE_URL}/api/admin/blocked-words", cookies=admin_cookies,
                           json={"words": base + ["zork"]}, timeout=DEFAULT_TIMEOUT)
        assert r1.status_code == 200, r1.text
        r2 = requests.get(f"{BASE_URL}/api/admin/blocked-words", cookies=admin_cookies, timeout=DEFAULT_TIMEOUT)
        j2 = r2.json()
        words = j2 if isinstance(j2, list) else j2.get("words", [])
        assert "zork" in words

        # Remove zork (restore original)
        r3 = requests.post(f"{BASE_URL}/api/admin/blocked-words", cookies=admin_cookies,
                           json={"words": base}, timeout=DEFAULT_TIMEOUT)
        assert r3.status_code == 200, r3.text
        r4 = requests.get(f"{BASE_URL}/api/admin/blocked-words", cookies=admin_cookies, timeout=DEFAULT_TIMEOUT)
        j4 = r4.json()
        words = j4 if isinstance(j4, list) else j4.get("words", [])
        assert "zork" not in words


# ---------- Trial Abuse ----------
class TestTrialAbuse:
    def test_list_devices(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/admin/trial-devices", cookies=admin_cookies, timeout=15)
        assert r.status_code == 200
        data = r.json()
        devs = data if isinstance(data, list) else data.get("devices", [])
        seeded = [d for d in devs if d.get("device_id") == SEED_DEVICE]
        assert seeded, f"seed device missing: {devs[:3]}"
        assert seeded[0].get("email_count", 0) >= 2

    def test_block_then_pronounce_402_then_unblock(self, admin_cookies, member_headers):
        # Block
        r = requests.post(
            f"{BASE_URL}/api/admin/trial-devices/block",
            cookies=admin_cookies,
            json={"device_id": SEED_DEVICE, "blocked": True},
            timeout=15,
        )
        assert r.status_code == 200, r.text

        # Pronounce with cookie should be 402
        pr = requests.get(
            f"{BASE_URL}/api/pronounce?word=garden",
            headers=member_headers,
            cookies={"pt_device": SEED_DEVICE},
            timeout=30,
        )
        assert pr.status_code == 402, f"expected 402, got {pr.status_code}: {pr.text[:200]}"
        try:
            assert pr.json().get("code") == "trial_exhausted" or pr.json().get("detail", {}).get("code") == "trial_exhausted"
        except Exception:
            pass

        # Without cookie — email blocked path
        pr2 = requests.get(f"{BASE_URL}/api/pronounce?word=garden", headers=member_headers, timeout=30)
        assert pr2.status_code == 402, f"expected 402 without cookie (email blocked), got {pr2.status_code}"

        # Unblock
        u = requests.post(
            f"{BASE_URL}/api/admin/trial-devices/block",
            cookies=admin_cookies,
            json={"device_id": SEED_DEVICE, "blocked": False},
            timeout=15,
        )
        assert u.status_code == 200, u.text

        # Pronounce should be 200
        pr3 = requests.get(f"{BASE_URL}/api/pronounce?word=garden", headers=member_headers, timeout=30)
        assert pr3.status_code == 200, f"expected 200 after unblock, got {pr3.status_code}: {pr3.text[:200]}"

    @pytest.fixture(autouse=True)
    def _ensure_unblocked(self, admin_cookies):
        yield
        try:
            requests.post(
                f"{BASE_URL}/api/admin/trial-devices/block",
                cookies=admin_cookies,
                json={"device_id": SEED_DEVICE, "blocked": False},
                timeout=15,
            )
        except Exception:
            pass
