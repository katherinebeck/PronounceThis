"""Unit tests for the Real Speakers caption profanity screen."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import profanity  # noqa: E402
from caption_search import CaptionSearchService  # noqa: E402


def _t(*rows):
    return [{"text": text, "start": float(s), "duration": float(d)} for text, s, d in rows]


def test_slur_anywhere_flags_video():
    assert profanity.has_slur(_t(("hello there", 0, 2), ("that nigga said", 300, 2)))
    assert not profanity.has_slur(_t(("nigeria and niger are countries", 0, 3)))
    assert not profanity.has_slur(_t(("a raccoon in the backyard", 0, 3)))


def test_bleep_marker_and_swears_are_profanity_only():
    tr = _t(("what the [ __ ] was that", 10, 3), ("this fucking server", 100, 3), ("a shitty day", 200, 2))
    assert not profanity.has_slur(tr)
    assert profanity.profane_spans(tr) == [(10.0, 13.0), (100.0, 103.0), (200.0, 202.0)]


def test_clip_window_check():
    spans = [(100.0, 103.0)]
    assert profanity.clip_is_clean(spans, 50.0)
    assert not profanity.clip_is_clean(spans, 90.0)   # within 20s before
    assert not profanity.clip_is_clean(spans, 120.0)  # within 20s after
    assert profanity.clip_is_clean(spans, 124.0)


def test_find_word_skips_dirty_clip_and_picks_clean_one():
    tr = _t(("the server is down", 10, 2), ("oh shit", 15, 1), ("call the server again", 300, 2))
    hit = CaptionSearchService._find_word_in_transcript(tr, "server")
    assert hit is not None
    assert hit["offset"] >= 300.0


def test_find_word_returns_none_when_every_clip_is_dirty():
    tr = _t(("the server is down", 10, 2), ("[ __ ]", 12, 1))
    assert CaptionSearchService._find_word_in_transcript(tr, "server") is None
