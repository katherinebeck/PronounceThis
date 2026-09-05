"""Tests for the magic-link error-handling fix (Cloudflare 5xx -> 4xx)."""
import os
import time
import uuid
import requests
import pytest

BASE_URL = "https://accent-coach-pro.preview.emergentagent.com"


@pytest.fixture
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestMagicLinkErrorMapping:
    def test_unverified_real_email_returns_400(self, client):
        email = f"randomtest{uuid.uuid4().hex[:8]}@gmail.com"
        r = client.post(f"{BASE_URL}/api/auth/request-magic-link", json={"email": email})
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("detail") == "email_delivery_pending_domain_verification", body

    def test_fake_domain_email_returns_400(self, client):
        email = f"tester{uuid.uuid4().hex[:6]}@example.com"
        r = client.post(f"{BASE_URL}/api/auth/request-magic-link", json={"email": email})
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail")
        assert detail in ("email_delivery_pending_domain_verification", "email_send_failed"), detail

    def test_invalid_email_returns_400_or_422(self, client):
        r = client.post(f"{BASE_URL}/api/auth/request-magic-link", json={"email": "not-an-email"})
        assert r.status_code in (400, 422), f"Expected 400/422, got {r.status_code}: {r.text}"

    def test_rate_limit_second_call_is_silent_ok(self, client):
        email = f"ratelimit{uuid.uuid4().hex[:8]}@gmail.com"
        r1 = client.post(f"{BASE_URL}/api/auth/request-magic-link", json={"email": email})
        # First call may 400 (Resend rejects), but it should still write a magic_link row.
        assert r1.status_code in (200, 400), f"First call unexpected: {r1.status_code} {r1.text}"
        # Second call within 60s must be silent 200 ok:true
        time.sleep(1)
        r2 = client.post(f"{BASE_URL}/api/auth/request-magic-link", json={"email": email})
        assert r2.status_code == 200, f"Expected 200 on rate-limit path, got {r2.status_code}: {r2.text}"
        assert r2.json() == {"ok": True}


class TestRegression:
    def test_auth_me_unauth_returns_200(self, client):
        r = client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        assert r.json().get("authenticated") is False

    def test_checkout_unauth_returns_401(self, client):
        r = client.post(f"{BASE_URL}/api/payments/checkout", json={"lookup_key": "accent_coach_monthly", "origin_url": BASE_URL})
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"

    def test_kajabi_webhook_unauth_returns_401(self, client):
        r = client.post(f"{BASE_URL}/api/kajabi/webhook", json={})
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
