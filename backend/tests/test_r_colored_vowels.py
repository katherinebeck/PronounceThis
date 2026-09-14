"""Vowel + syllable-closing R (or ER) is r-colored: Rhotic R list only."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from phonetics import classify_word, classify_ipa, get_arpabet


@pytest.mark.parametrize("word,excluded", [
    ("star", "v_aa"), ("for", "v_ao"), ("air", "v_eh"), ("here", "v_iy"),
    ("poor", "v_uw"), ("card", "v_aa"),
    ("fire", "d_ay"), ("hour", "d_aw"), ("player", "d_ey"),
])
def test_r_colored_vowel_is_r_only(word, excluded):
    cats = classify_word(get_arpabet(word))
    assert "rhotic_r" in cats
    assert excluded not in cats


@pytest.mark.parametrize("word,kept", [
    ("very", "v_eh"), ("sorry", "v_aa"), ("mary", "v_eh"), ("hero", "v_ih"),
    ("starry", "v_aa"), ("father", "v_aa"),
])
def test_syllable_boundary_r_keeps_vowel(word, kept):
    cats = classify_word(get_arpabet(word))
    assert "rhotic_r" in cats
    assert kept in cats


def test_classify_ipa_r_colored():
    assert classify_ipa("stɑɹ") == ["consonant_t", "rhotic_r"]
    assert "d_ay" not in classify_ipa("ˈfaɪɚ")
    assert "v_eh" in classify_ipa("ˈvɛɹi")
    assert "v_aa" in classify_ipa("ˈfɑðɚ")
