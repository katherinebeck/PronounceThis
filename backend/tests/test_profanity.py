"""Unit tests for the Real Speakers slur screen (swearing is allowed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import profanity  # noqa: E402
from caption_search import CaptionSearchService  # noqa: E402


def _t(*rows):
    return [{"text": text, "start": float(s), "duration": float(d)} for text, s, d in rows]


def test_slur_anywhere_flags_video():
    assert profanity.has_slur(_t(("hello there", 0, 2), ("that nigga said", 300, 2)))
    assert profanity.has_slur(_t(("he used the word nigger on air", 5, 2)))


def test_no_false_positives_on_lookalikes_and_surnames():
    assert not profanity.has_slur(_t(("nigeria and niger are countries", 0, 3)))
    assert not profanity.has_slur(_t(("senator coons and dick van dyke", 0, 3)))
    assert not profanity.has_slur(_t(("a raccoon in the backyard", 0, 3)))


def test_swearing_is_not_flagged():
    assert not profanity.has_slur(_t(("what the [ __ ] was that", 10, 3), ("this fucking server", 100, 3)))


def test_find_word_ignores_nearby_swearing():
    tr = _t(("the server is down", 10, 2), ("oh shit", 11, 1))
    hit = CaptionSearchService._find_word_in_transcript(tr, "server")
    assert hit is not None and 10.0 <= hit["offset"] < 12.0
