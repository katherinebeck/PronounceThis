"""Tests for GET /api/pronounce endpoint."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def session():
    return requests.Session()


# --- Happy path: CMU dictionary ---
class TestPronounceCMU:
    def test_butter(self, session):
        r = session.get(f"{API}/pronounce", params={"word": "butter"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["word"] == "butter"
        assert d["normalized"] == "butter"
        assert d["source"] == "cmu"
        assert d["ipa"] and isinstance(d["ipa"], str)
        # ARPABET should be exactly the CMU sequence
        assert d["arpabet"] == ["B", "AH1", "T", "ER0"]
        cats = set(d["categories"])
        assert "rhotic_r" in cats
        assert "flap_t" in cats
        assert "consonant_t" in cats

    def test_whitmore_proper_noun(self, session):
        r = session.get(f"{API}/pronounce", params={"word": "Whitmore"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["word"] == "Whitmore"
        assert d["normalized"] == "whitmore"
        assert d["source"] == "cmu"
        assert d["ipa"] is not None and len(d["ipa"]) > 0
        assert "rhotic_r" in d["categories"]

    def test_case_insensitive(self, session):
        results = []
        for w in ["BUTTER", "Butter", "butter"]:
            r = session.get(f"{API}/pronounce", params={"word": w}, timeout=15)
            assert r.status_code == 200
            results.append(r.json())
        # all normalize/ipa/arpabet same
        assert results[0]["ipa"] == results[1]["ipa"] == results[2]["ipa"]
        assert results[0]["arpabet"] == results[1]["arpabet"] == results[2]["arpabet"]
        assert all(x["normalized"] == "butter" for x in results)


# --- LLM fallback / none ---
class TestPronounceFallback:
    def test_out_of_dict_word(self, session):
        r = session.get(f"{API}/pronounce", params={"word": "xyzzytest"}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["normalized"] == "xyzzytest"
        assert d["source"] in ("llm", "none")
        if d["source"] == "llm":
            assert d["ipa"] and isinstance(d["ipa"], str)
        else:
            assert d["ipa"] is None


# --- Validation errors ---
class TestPronounceValidation:
    def test_empty_word(self, session):
        r = session.get(f"{API}/pronounce", params={"word": ""}, timeout=15)
        assert r.status_code == 400
        assert "word is required" in r.json().get("detail", "").lower()

    def test_whitespace_only(self, session):
        r = session.get(f"{API}/pronounce", params={"word": "   "}, timeout=15)
        assert r.status_code == 400

    def test_punctuation_only(self, session):
        r = session.get(f"{API}/pronounce", params={"word": "!!!"}, timeout=15)
        assert r.status_code == 400
        detail = r.json().get("detail", "").lower()
        assert "real word" in detail


# --- Regression: existing endpoints still healthy ---
class TestRegression:
    def test_root(self, session):
        r = session.get(f"{API}/", timeout=15)
        assert r.status_code == 200

    def test_sound_categories(self, session):
        r = session.get(f"{API}/sound-categories", timeout=15)
        assert r.status_code == 200
        assert "categories" in r.json()

    def test_scenes_list(self, session):
        r = session.get(f"{API}/scenes", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_laundry_list(self, session):
        # Use one known scene id? Just check endpoint exists via a bogus id -> 404 acceptable
        r = session.get(f"{API}/laundry-list", timeout=15)
        # endpoint may require params - accept 200/400/404/422
        assert r.status_code in (200, 400, 404, 422)
