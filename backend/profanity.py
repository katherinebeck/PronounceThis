"""Caption profanity screen for Real Speakers clips.

Two tiers:
- SLURS: a video whose transcript contains one anywhere is excluded outright.
- PROFANITY (incl. YouTube's "[ __ ]" bleep marker): a clip is skipped only
  if it lands inside the window the student actually hears.
"""
import re
from typing import Any, Dict, List, Tuple

SLUR_RE = re.compile(
    r"\b(?:nigg(?:a|ah|er|uh)s?|faggots?|fags?|kikes?|spi(?:c|ck)s?|wetbacks?|gooks?|"
    r"trann(?:y|ies)|retard(?:ed|s)?|chinks?|towelheads?|ragheads?|beaners?|"
    r"pakis?|jigaboos?|darkies?|zipperheads?)\b",
    re.IGNORECASE,
)

PROFANITY_RE = re.compile(
    r"\[\s*_+\s*\]"  # YouTube auto-caption bleep marker
    r"|\b(?:f+u+c+k\w*|mother\s?fuck\w*|shit\w*|bullshit|bitch\w*|assholes?|cunts?|"
    r"dick(?:head)?s?|puss(?:y|ies)|cock(?:sucker)?s?|god?damn\w*|bastards?|whores?|"
    r"sluts?|twats?|jackass(?:es)?|dumbass(?:es)?|wankers?|pricks?)\b",
    re.IGNORECASE,
)

CLIP_WINDOW_SECONDS = 20.0


def has_slur(transcript: List[Dict[str, Any]]) -> bool:
    return any(SLUR_RE.search(e.get("text") or "") for e in transcript or [])


def profane_spans(transcript: List[Dict[str, Any]]) -> List[Tuple[float, float]]:
    """(start, end) of every caption chunk containing profanity or a slur."""
    spans: List[Tuple[float, float]] = []
    for e in transcript or []:
        text = e.get("text") or ""
        if PROFANITY_RE.search(text) or SLUR_RE.search(text):
            start = float(e.get("start", 0) or 0)
            spans.append((start, start + float(e.get("duration", 0) or 0)))
    return spans


def clip_is_clean(spans: List[Tuple[float, float]], offset: float,
                  window: float = CLIP_WINDOW_SECONDS) -> bool:
    lo, hi = offset - window, offset + window
    return not any(s <= hi and e >= lo for s, e in spans)
