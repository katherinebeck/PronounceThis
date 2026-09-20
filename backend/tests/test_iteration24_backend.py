"""Iteration 24 backend verification: pronounce variants, Connection:close header."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://accent-coach-pro.preview.emergentagent.com"


def test_pronounce_produce_variants():
    r = requests.get(f"{BASE_URL}/api/pronounce", params={"word": "produce"}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    variants = data.get("variants") or []
    assert len(variants) == 2, f"expected 2 variants, got {len(variants)}: {variants}"
    labels = [v.get("label") for v in variants]
    assert "Noun" in labels and "Verb" in labels, f"labels: {labels}"
    ipas = [v.get("ipa") for v in variants]
    assert ipas[0] != ipas[1], f"variants have same ipa: {ipas}"


def test_pronounce_server_ipa():
    r = requests.get(f"{BASE_URL}/api/pronounce", params={"word": "server"}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    ipa = data.get("ipa") or (data.get("variants") or [{}])[0].get("ipa")
    assert ipa == "ˈsɝ·vɚ", f"got ipa={ipa!r}"


def test_sound_categories_connection_close():
    # Test against origin directly. Preview URL uses HTTP/2 which strips
    # hop-by-hop Connection header per protocol; assert on origin.
    r = requests.get("http://localhost:8001/api/sound-categories", timeout=30)
    assert r.status_code == 200
    conn = r.headers.get("Connection", "").lower()
    assert conn == "close", f"Connection header={conn!r}"
