"""Phonetic engine: ARPABET -> American English IPA, plus sound-category
classification used to build "laundry lists" for accent practice.

Uses the CMU Pronouncing Dictionary via the `pronouncing` library as the
primary source, and exposes helpers to detect specific American-accent
phenomena (rhotic R, light vs dark L, flap T, schwa, diphthongs, etc.).
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

import pronouncing

# ---- ARPABET -> IPA (General American) -------------------------------------
ARPA_TO_IPA = {
    # Vowels (monophthongs / r-colored / diphthongs)
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ",
    "AW": "aʊ", "AY": "aɪ",
    "EH": "ɛ", "ER": "ɝ", "EY": "eɪ",
    "IH": "ɪ", "IY": "i",
    "OW": "oʊ", "OY": "ɔɪ",
    "UH": "ʊ", "UW": "u",
    # Consonants
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð",
    "F": "f", "G": "ɡ", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m",
    "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ",
    "S": "s", "SH": "ʃ", "T": "t", "TH": "θ",
    "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}

VOWEL_ARPA = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER",
    "EY", "IH", "IY", "OW", "OY", "UH", "UW",
}

DIPHTHONG_ARPA = {"AW", "AY", "EY", "OW", "OY"}


# ---- ARPABET -> "read-me-like-English" respelling --------------------------
# Used to nudge ElevenLabs into the right pronunciation for words it
# regularly misreads from the spelling (e.g. "direction" → "dye-rection"
# instead of "duh-REK-shun"). We send the respelling in place of the word;
# ElevenLabs reads it phonetically because SSML <phoneme> tags aren't
# supported by the multilingual_v2 model.
ARPA_TO_RESPELL = {
    # Vowels
    "AA": "ah",   # father
    "AE": "a",    # cat
    "AH": "uh",   # sun / schwa (unstressed reduces below)
    "AO": "aw",   # thought
    "AW": "ow",   # cow
    "AY": "eye",  # my
    "EH": "eh",   # bet
    "ER": "er",   # her
    "EY": "ay",   # say
    "IH": "ih",   # sit
    "IY": "ee",   # see
    "OW": "oh",   # go
    "OY": "oy",   # boy
    "UH": "uu",   # book
    "UW": "oo",   # boot
    # Consonants
    "B": "b", "CH": "ch", "D": "d", "DH": "th",
    "F": "f", "G": "g", "HH": "h",
    "JH": "j", "K": "k", "L": "l", "M": "m",
    "N": "n", "NG": "ng", "P": "p", "R": "r",
    "S": "s", "SH": "sh", "T": "t", "TH": "th",
    "V": "v", "W": "w", "Y": "y", "Z": "z", "ZH": "zh",
}


def arpabet_to_respelling(arp: List[str]) -> str:
    """Convert an ARPABET phoneme sequence to an English-readable respelling
    like ``duh-REK-shun``. Syllables split around vowels; the primary-stressed
    syllable is UPPERCASE so ElevenLabs places the accent correctly."""
    if not arp:
        return ""

    # Split phonemes into syllables: each vowel anchors a syllable, with the
    # preceding consonants as the onset. Trailing consonants attach to the
    # last vowel.
    syllables: List[List[str]] = []
    current: List[str] = []
    for ph in arp:
        base = re.sub(r"\d", "", ph)
        stress = ph[-1] if ph[-1].isdigit() else ""
        if base in VOWEL_ARPA:
            if current:
                syllables.append(current)
            current = [ph]
        else:
            current.append(ph)
    if current:
        syllables.append(current)

    # If we still have a leading consonant-only chunk, glue it to syllable 1.
    if len(syllables) >= 2:
        first_base = re.sub(r"\d", "", syllables[0][0])
        if first_base not in VOWEL_ARPA:
            syllables[1] = syllables[0] + syllables[1]
            syllables.pop(0)

    def _syllable_text(phs: List[str]) -> Tuple[str, int]:
        """Render one syllable and return (text, stress_level 0|1|2)."""
        letters: List[str] = []
        stress = 0
        for ph in phs:
            base = re.sub(r"\d", "", ph)
            if ph[-1].isdigit():
                stress = max(stress, int(ph[-1]))
            # Schwa: unstressed AH becomes "uh" (already), but a truly reduced
            # AH0 sounds most natural as "uh".
            letters.append(ARPA_TO_RESPELL.get(base, base.lower()))
        return "".join(letters), stress

    rendered = [_syllable_text(s) for s in syllables]
    if not rendered:
        return ""

    # Locate primary stress. If none marked, fall back to the first syllable.
    stressed_idx = next(
        (i for i, (_, s) in enumerate(rendered) if s == 1),
        0,
    )
    parts: List[str] = []
    for i, (text, _) in enumerate(rendered):
        parts.append(text.upper() if i == stressed_idx else text)
    return "-".join(parts)


def strip_stress(phone: str) -> str:
    """Remove the trailing 0/1/2 stress marker from an ARPABET phone."""
    return re.sub(r"\d", "", phone)


# Coach-preferred pronunciations (word -> ARPABET string). Seeded with
# cases where CMU's first entry isn't the General American citation form;
# extended at runtime from the `pronunciation_prefs` collection via Admin.
PREFERRED_ARPA: dict = {
    "because": "B IH0 K AH1 Z",
}


def cmu_variants(word: str) -> List[List[str]]:
    """All CMU pronunciations for a word (may be empty)."""
    return [p.split() for p in pronouncing.phones_for_word(word.lower().strip())]


def validate_arpabet(text: str) -> Optional[List[str]]:
    """Parse 'B IH0 K AH1 Z' -> phones list, or None if any phone is unknown."""
    phones = [p.strip().upper() for p in (text or "").replace(",", " ").split() if p.strip()]
    if not phones:
        return None
    for p in phones:
        bare = strip_stress(p)
        if bare not in ARPA_TO_IPA:
            return None
        if bare in VOWEL_ARPA and p[-1:] not in ("0", "1", "2"):
            return None
    return phones


def get_arpabet(word: str) -> Optional[List[str]]:
    """Return the first CMU pronunciation as a list of ARPABET phones, or None."""
    w = word.lower().strip()
    if not w:
        return None
    if w in PREFERRED_ARPA:
        return PREFERRED_ARPA[w].split()
    pronunciations = pronouncing.phones_for_word(w)
    if not pronunciations:
        return None
    return pronunciations[0].split()


def arpabet_to_ipa(phones: List[str]) -> str:
    """Convert an ARPABET phone list to a compact American IPA string.

    Stress markers: primary -> ˈ, secondary -> ˌ, prefixed before the syllable
    onset of the stressed vowel. We use a simple syllable-agnostic placement:
    the marker is placed immediately before the stressed vowel symbol.
    Unstressed AH (AH0) is rendered as the schwa ə, mirroring General American.
    """
    out: List[str] = []
    for p in phones:
        m = re.match(r"^([A-Z]+)(\d?)$", p)
        if not m:
            continue
        base, stress = m.group(1), m.group(2)
        if base == "AH" and stress == "0":
            ipa = "ə"
        else:
            ipa = ARPA_TO_IPA.get(base, "")
        if stress == "1":
            out.append("ˈ" + ipa)
        elif stress == "2":
            out.append("ˌ" + ipa)
        else:
            out.append(ipa)
    return "".join(out)


# ---- Sound classification --------------------------------------------------

SOUND_CATEGORIES = [
    # Consonants
    {"id": "consonant_l", "label": "L", "ipa": "l / ɫ",
     "description": "Every word containing the L consonant (light or dark)."},
    {"id": "consonant_t", "label": "T", "ipa": "t",
     "description": "Every word containing a T sound."},
    {"id": "rhotic_r", "label": "Rhotic R", "ipa": "ɹ / ɝ",
     "description": "Words containing the American R consonant or r-colored vowel."},
    # Vowels
    {"id": "v_iy", "label": "i — see", "ipa": "i", "description": "The 'see' vowel."},
    {"id": "v_ih", "label": "ɪ — sit", "ipa": "ɪ", "description": "The 'sit' vowel."},
    {"id": "v_eh", "label": "ɛ — bet", "ipa": "ɛ", "description": "The 'bet' vowel."},
    {"id": "v_ae", "label": "æ — cat", "ipa": "æ", "description": "The 'cat' vowel."},
    {"id": "v_schwa", "label": "ə — schwa", "ipa": "ə",
     "description": "The unstressed neutral vowel — the most common sound in English."},
    {"id": "v_uh_stressed", "label": "ʌ — cup", "ipa": "ʌ", "description": "The stressed 'cup' vowel."},
    {"id": "v_uw", "label": "u — boot", "ipa": "u", "description": "The 'boot' vowel."},
    {"id": "v_uh", "label": "ʊ — book", "ipa": "ʊ", "description": "The 'book' vowel."},
    {"id": "v_ao", "label": "ɔ — thought", "ipa": "ɔ", "description": "The 'thought' vowel."},
    {"id": "v_aa", "label": "ɑ — father", "ipa": "ɑ", "description": "The 'father / lot' vowel."},
    # Diphthongs — one list each
    {"id": "d_ey", "label": "eɪ — say", "ipa": "eɪ", "description": "As in 'say'."},
    {"id": "d_ay", "label": "aɪ — my", "ipa": "aɪ", "description": "As in 'my'."},
    {"id": "d_ow", "label": "oʊ — go", "ipa": "oʊ", "description": "As in 'go'."},
    {"id": "d_aw", "label": "aʊ — cow", "ipa": "aʊ", "description": "As in 'cow'."},
    {"id": "d_oy", "label": "ɔɪ — boy", "ipa": "ɔɪ", "description": "As in 'boy'."},
]

_ARPA_CATEGORY = {
    "L": "consonant_l", "T": "consonant_t",
    "IY": "v_iy", "IH": "v_ih", "EH": "v_eh", "AE": "v_ae",
    "UW": "v_uw", "UH": "v_uh", "AO": "v_ao", "AA": "v_aa",
    "EY": "d_ey", "AY": "d_ay", "OW": "d_ow", "AW": "d_aw", "OY": "d_oy",
}

# IPA symbol -> category, for LLM-transcribed words with no ARPABET.
# Diphthongs listed first so "eɪ" is consumed before the bare "ɪ".
_IPA_CATEGORY = [
    ("eɪ", "d_ey"), ("aɪ", "d_ay"), ("oʊ", "d_ow"), ("aʊ", "d_aw"), ("ɔɪ", "d_oy"),
    ("ɹ", "rhotic_r"), ("ɝ", "rhotic_r"), ("ɚ", "rhotic_r"),
    ("ɫ", "consonant_l"), ("l", "consonant_l"), ("t", "consonant_t"), ("ɾ", "consonant_t"),
    ("i", "v_iy"), ("ɪ", "v_ih"), ("ɛ", "v_eh"), ("æ", "v_ae"), ("ə", "v_schwa"),
    ("ʌ", "v_uh_stressed"), ("u", "v_uw"), ("ʊ", "v_uh"), ("ɔ", "v_ao"), ("ɑ", "v_aa"),
]

_CATEGORY_ORDER = [c["id"] for c in SOUND_CATEGORIES]


def _has_phone(phones: List[str], target: str) -> bool:
    return any(strip_stress(p) == target for p in phones)


def _is_vowel(p: str) -> bool:
    return strip_stress(p) in VOWEL_ARPA


def classify_word(phones: List[str]) -> List[str]:
    """Return the list of sound-category ids a word belongs to."""
    if not phones:
        return []
    cats: set = set()
    for p in phones:
        bare = strip_stress(p)
        if bare in ("R", "ER"):
            cats.add("rhotic_r")
        elif bare == "AH":
            cats.add("v_schwa" if p.endswith("0") else "v_uh_stressed")
        elif bare in _ARPA_CATEGORY:
            cats.add(_ARPA_CATEGORY[bare])
    return [c for c in _CATEGORY_ORDER if c in cats]


def classify_ipa(ipa: Optional[str]) -> List[str]:
    """Best-effort categories from an IPA string (LLM fallback words)."""
    if not ipa:
        return []
    rest = ipa
    cats: set = set()
    for sym, cat in _IPA_CATEGORY:
        if sym in rest:
            cats.add(cat)
            rest = rest.replace(sym, " ")
    return [c for c in _CATEGORY_ORDER if c in cats]


def transcribe_word(word: str) -> Tuple[Optional[str], List[str], List[str]]:
    """Return (ipa, arpabet_phones, sound_categories) for a single word.

    Returns (None, [], []) if the word is not in the CMU dictionary; the caller
    can then fall back to an LLM-based transcription.
    """
    phones = get_arpabet(word)
    if not phones:
        return None, [], []
    return arpabet_to_ipa(phones), phones, classify_word(phones)
