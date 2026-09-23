"""Slur screen for Real Speakers clips: a video whose captions contain a
slur anywhere is excluded outright. Ordinary swearing is allowed (actors
need it). Surnames like Coons / Dyke are deliberately not listed."""
import re
from typing import Any, Dict, List

SLUR_RE = re.compile(
    r"\b(?:nigg(?:a|ah|er|uh)s?|faggots?|fags?|kikes?|spi(?:c|ck)s?|wetbacks?|gooks?|"
    r"trann(?:y|ies)|retard(?:ed|s)?|chinks?|towelheads?|ragheads?|beaners?|"
    r"pakis?|jigaboos?|darkies?|zipperheads?)\b",
    re.IGNORECASE,
)


def has_slur(transcript: List[Dict[str, Any]]) -> bool:
    return any(SLUR_RE.search(e.get("text") or "") for e in transcript or [])
