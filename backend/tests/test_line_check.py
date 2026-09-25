"""Unit tests for the scene-line self-check comparison logic (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import line_check  # noqa: E402

LINE = "Look, the whole faculty knows that you've had a difficult couple of years."


def test_exact_and_punctuation_variants_match():
    assert line_check.line_matches(LINE, "look the whole faculty knows that you've had a difficult couple of years")
    assert line_check.line_matches(LINE, "Look — the whole faculty knows that you have had a difficult couple of years!")


def test_echoed_word_glitch_is_caught():
    assert not line_check.line_matches(LINE, "Look, the whole faculty knows that you've had a difficult couple you've years.")
    bad = line_check.mismatches(LINE, "Look, the whole faculty knows that you've had a difficult couple you've years.")
    assert bad and bad[0][1] == ["of"]


def test_dropped_word_is_caught():
    assert not line_check.line_matches(LINE, "Look, the whole faculty knows that you've had a difficult couple years.")


def test_stt_noise_numbers_and_parentheticals_are_forgiven():
    script = "(beat) You've missed 12 classes this term alone, Leila. Twelve."
    assert line_check.line_matches(script, "You have missed twelve classes this term alone, Leila. 12.")
    assert line_check.line_matches("That's why I'm on your side, kiddo.", "Um, that's why I'm on your side kiddo")
    assert line_check.line_matches("You stopped going to the grief counsellor?", "You stopped going to the grief counselor?")
    assert line_check.line_matches("Mr. Turner, I'm fine.", "Mister Turner I am fine")


def test_wrong_name_is_caught():
    assert not line_check.line_matches("Mr. Turner, I'm fine.", "Mr. Werner, I'm fine.")


def test_homophone_and_name_spelling_drift_are_forgiven():
    assert line_check.line_matches("I'm not alone. I have Abbie.", "I'm not alone. I have Abby.")
    assert line_check.line_matches("Leila, sit down.", "Layla, sit down.")
    assert not line_check.line_matches("Of course.", "Off course.")
    assert line_check.line_matches("We'd die for each other.", "We die for each other.")
    assert not line_check.line_matches("I don't know her.", "I do know her.")
    assert line_check.line_matches("Be as openminded as you can, we, uh, grab on.", "Be as open-minded as you can, we grab on.")
