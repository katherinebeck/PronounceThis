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


def get_arpabet(word: str) -> Optional[List[str]]:
    """Return the first CMU pronunciation as a list of ARPABET phones, or None."""
    w = word.lower().strip()
    if not w:
        return None
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
    {"id": "rhotic_r", "label": "Rhotic R", "ipa": "ɹ / ɝ",
     "description": "Words containing the American R consonant or r-colored vowel."},
    {"id": "light_l", "label": "Light L", "ipa": "l (onset)",
     "description": "L at the start of a syllable, before a vowel — a clearer, brighter L."},
    {"id": "dark_l", "label": "Dark L", "ipa": "ɫ (coda)",
     "description": "L at the end of a syllable or before a consonant — velarized, heavier."},
    {"id": "flap_t", "label": "Flap T", "ipa": "ɾ",
     "description": "T (or D) between vowels, realized as an alveolar tap in American English."},
    {"id": "schwa", "label": "Schwa", "ipa": "ə",
     "description": "The unstressed neutral vowel — the most common sound in English."},
    {"id": "diphthongs", "label": "Diphthongs", "ipa": "aɪ aʊ eɪ oʊ ɔɪ",
     "description": "Vowels that glide from one quality to another within a single syllable."},
    {"id": "ae", "label": "Short A (æ)", "ipa": "æ", "description": "The 'cat' vowel."},
    {"id": "ah", "label": "Open A (ɑ)", "ipa": "ɑ", "description": "The 'father / lot' vowel."},
    {"id": "th_voiceless", "label": "Voiceless TH", "ipa": "θ", "description": "As in 'think'."},
    {"id": "th_voiced", "label": "Voiced TH", "ipa": "ð", "description": "As in 'this'."},
    {"id": "sh", "label": "SH", "ipa": "ʃ", "description": "As in 'ship'."},
    {"id": "zh", "label": "ZH", "ipa": "ʒ", "description": "As in 'measure'."},
    {"id": "ch", "label": "CH", "ipa": "tʃ", "description": "As in 'church'."},
    {"id": "ng", "label": "NG", "ipa": "ŋ", "description": "As in 'sing'."},
    {"id": "consonant_l", "label": "All L's", "ipa": "l",
     "description": "Every word containing the L consonant."},
    {"id": "consonant_t", "label": "All T's", "ipa": "t",
     "description": "Every word containing a T sound."},
    {"id": "consonant_d", "label": "All D's", "ipa": "d", "description": "Every word with D."},
    {"id": "consonant_s", "label": "S", "ipa": "s", "description": "Every word with S."},
    {"id": "consonant_z", "label": "Z", "ipa": "z", "description": "Every word with Z."},
]


def _has_phone(phones: List[str], target: str) -> bool:
    return any(strip_stress(p) == target for p in phones)


def _is_vowel(p: str) -> bool:
    return strip_stress(p) in VOWEL_ARPA


def classify_word(phones: List[str]) -> List[str]:
    """Return the list of sound-category ids a word belongs to."""
    if not phones:
        return []
    cats: List[str] = []
    bare = [strip_stress(p) for p in phones]

    if "R" in bare or "ER" in bare:
        cats.append("rhotic_r")

    # Light vs Dark L: examine each L's position.
    for i, p in enumerate(bare):
        if p != "L":
            continue
        nxt = bare[i + 1] if i + 1 < len(bare) else None
        prev = bare[i - 1] if i - 1 >= 0 else None
        if nxt and nxt in VOWEL_ARPA:
            if "light_l" not in cats:
                cats.append("light_l")
        else:
            # End of word OR before a consonant; if preceded by a vowel it's
            # the prototypical dark/velarized L.
            if prev and prev in VOWEL_ARPA:
                if "dark_l" not in cats:
                    cats.append("dark_l")
            else:
                if "dark_l" not in cats:
                    cats.append("dark_l")

    # Flap T: T (or D) between two vowels — classic American flapping.
    for i, p in enumerate(bare):
        if p in ("T", "D") and 0 < i < len(bare) - 1:
            if bare[i - 1] in VOWEL_ARPA and bare[i + 1] in VOWEL_ARPA:
                cats.append("flap_t")
                break

    # Schwa = unstressed AH (AH0).
    if any(p == "AH" and phones[i].endswith("0") for i, p in enumerate(bare)):
        cats.append("schwa")

    if any(p in DIPHTHONG_ARPA for p in bare):
        cats.append("diphthongs")

    simple_map = {
        "AE": "ae", "AA": "ah",
        "TH": None, "DH": "th_voiced",
        "SH": "sh", "ZH": "zh", "CH": "ch", "NG": "ng",
        "L": "consonant_l", "T": "consonant_t", "D": "consonant_d",
        "S": "consonant_s", "Z": "consonant_z",
    }
    for arpa, cat_id in simple_map.items():
        if cat_id is None:
            continue
        if arpa in bare and cat_id not in cats:
            cats.append(cat_id)
    if "TH" in bare and "th_voiceless" not in cats:
        cats.append("th_voiceless")

    return cats


def transcribe_word(word: str) -> Tuple[Optional[str], List[str], List[str]]:
    """Return (ipa, arpabet_phones, sound_categories) for a single word.

    Returns (None, [], []) if the word is not in the CMU dictionary; the caller
    can then fall back to an LLM-based transcription.
    """
    phones = get_arpabet(word)
    if not phones:
        return None, [], []
    return arpabet_to_ipa(phones), phones, classify_word(phones)
