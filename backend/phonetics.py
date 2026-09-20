"""Phonetic engine: ARPABET -> American English IPA, plus sound-category
classification used to build "laundry lists" for accent practice.

Uses the CMU Pronouncing Dictionary via the `pronouncing` library as the
primary source, and exposes helpers to detect specific American-accent
phenomena (rhotic R, light vs dark L, flap T, schwa, diphthongs, etc.).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

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


_IPA_TOKENS = [
    ("aɪ", "AY"), ("aʊ", "AW"), ("ɔɪ", "OY"), ("eɪ", "EY"), ("oʊ", "OW"),
    ("tʃ", "CH"), ("dʒ", "JH"), ("l̩", "L̩"), ("n̩", "N̩"), ("m̩", "M̩"),
    ("ɑ", "AA"), ("æ", "AE"), ("ʌ", "AH"), ("ə", "AH"), ("ɐ", "AH"), ("ɔ", "AO"),
    ("ɛ", "EH"), ("ɝ", "ER"), ("ɚ", "ER"), ("ɜ", "ER"), ("ɪ", "IH"), ("i", "IY"),
    ("ʊ", "UH"), ("u", "UW"), ("o", "OW"), ("e", "EY"), ("a", "AE"),
    ("b", "B"), ("d", "D"), ("ð", "DH"), ("f", "F"), ("ɡ", "G"), ("g", "G"),
    ("h", "HH"), ("ɦ", "HH"), ("k", "K"), ("l", "L"), ("ɫ", "L"), ("m", "M"),
    ("n", "N"), ("ŋ", "NG"), ("p", "P"), ("ɹ", "R"), ("r", "R"), ("s", "S"),
    ("ʃ", "SH"), ("t", "T"), ("ɾ", "T"), ("ʔ", "T"), ("θ", "TH"), ("v", "V"),
    ("w", "W"), ("j", "Y"), ("z", "Z"), ("ʒ", "ZH"),
]


def ipa_to_arpabet(ipa: str) -> Optional[List[str]]:
    """Best-effort inverse of arpabet_to_ipa for coach-edited IPA.

    ˈ/ˌ stress the next vowel (1/2); ə/ɚ are 0; ɝ is 1; other vowels are 0
    unless the word has no stress at all, then the first full vowel gets 1.
    Returns None if any symbol is unknown."""
    s = (ipa or "").strip().strip("/[]")
    s = s.replace("ː", "").replace("ˑ", "").replace("·", " ").replace(".", " ")
    if not s:
        return None
    out: List[str] = []
    pending: Optional[str] = None
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in " \t\u0303":
            i += 1
            continue
        if ch in "ˈˌ":
            pending = "1" if ch == "ˈ" else "2"
            i += 1
            continue
        for sym, arp in _IPA_TOKENS:
            if s.startswith(sym, i):
                if arp.endswith("\u0329"):
                    out.extend(["AH0", arp[0]])
                elif arp in VOWEL_ARPA:
                    if pending is not None:
                        stress, pending = pending, None
                    elif sym in ("ə", "ɚ"):
                        stress = "0"
                    elif sym == "ɝ":
                        stress = "1"
                    else:
                        stress = "0"
                    out.append(arp + stress)
                else:
                    out.append(arp)
                i += len(sym)
                break
        else:
            return None
    if not out:
        return None
    vowels = [k for k, p in enumerate(out) if strip_stress(p) in VOWEL_ARPA]
    if vowels and not any(out[k].endswith(("1", "2")) for k in vowels):
        target = next((k for k in vowels if out[k] != "AH0"), vowels[0])
        out[target] = strip_stress(out[target]) + "1"
    return out


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


# ---- Heteronyms: same spelling, different pronunciation by part of speech --

# Noun/verb pairs whose only difference is stress placement (PRO-duce vs
# pro-DUCE). Both variants come from CMU; we just decide which is which by
# where the primary stress falls.
_STRESS_SHIFT_WORDS = {
    "address", "affix", "ally", "combine", "compound", "compress", "concert",
    "conduct", "conflict", "console", "construct", "content", "contest",
    "contract", "contrast", "converse", "convert", "convict", "decrease",
    "defect", "desert", "digest", "discharge", "discount", "escort", "essay",
    "exploit", "extract", "ferment", "impact", "implant", "import", "imprint",
    "incense", "incline", "increase", "insert", "insult", "intrigue", "object",
    "perfect", "permit", "pervert", "present", "produce", "progress", "project",
    "protest", "rebel", "recall", "recess", "record", "refund", "refuse",
    "reject", "research", "retake", "segment", "subject", "survey", "suspect",
    "torment", "transfer", "transport", "update", "upgrade", "upset",
}
# First-syllable-stress label when it isn't simply "Noun".
_FIRST_STRESS_LABEL = {
    "perfect": "Adjective", "content": "Adjective / Noun", "present": "Noun / Adjective",
    "compound": "Noun / Adjective", "converse": "Adjective / Noun", "upset": "Noun / Adjective",
    "rebel": "Noun", "ally": "Noun", "essay": "Noun", "research": "Noun",
}

# Pairs where the vowel itself changes, or CMU lacks one of the two forms.
# (label, gloss, ARPABET)
_MANUAL_HETERONYMS: Dict[str, List[Tuple[str, str, str]]] = {
    "export":    [("Noun", "the goods", "EH1 K S P AO0 R T"), ("Verb", "to ship abroad", "IH0 K S P AO1 R T")],
    "invite":    [("Noun", "an invitation (casual)", "IH1 N V AY0 T"), ("Verb", "to ask someone", "IH0 N V AY1 T")],
    "entrance":  [("Noun", "a doorway", "EH1 N T R AH0 N S"), ("Verb", "to enchant", "IH0 N T R AE1 N S")],
    "read":      [("Present tense", "I read every day", "R IY1 D"), ("Past tense", "I read it yesterday", "R EH1 D")],
    "lead":      [("Verb", "to guide", "L IY1 D"), ("Noun", "the metal", "L EH1 D")],
    "live":      [("Verb", "to be alive", "L IH1 V"), ("Adjective", "a live show", "L AY1 V")],
    "close":     [("Verb", "to shut", "K L OW1 Z"), ("Adjective", "nearby", "K L OW1 S")],
    "wind":      [("Noun", "the weather", "W IH1 N D"), ("Verb", "to wind a clock", "W AY1 N D")],
    "bow":       [("Verb / Noun", "to bend; front of a ship", "B AW1"), ("Noun", "a ribbon or weapon", "B OW1")],
    "tear":      [("Verb / Noun", "to rip", "T EH1 R"), ("Noun", "a teardrop", "T IH1 R")],
    "bass":      [("Noun", "the fish", "B AE1 S"), ("Noun", "the instrument / low voice", "B EY1 S")],
    "dove":      [("Noun", "the bird", "D AH1 V"), ("Verb", "past tense of dive", "D OW1 V")],
    "sow":       [("Verb", "to plant seeds", "S OW1"), ("Noun", "a female pig", "S AW1")],
    "wound":     [("Noun / Verb", "an injury", "W UW1 N D"), ("Verb", "past tense of wind", "W AW1 N D")],
    "row":       [("Noun / Verb", "a line; to row a boat", "R OW1"), ("Noun", "a quarrel", "R AW1")],
    "use":       [("Verb", "to use something", "Y UW1 Z"), ("Noun", "the use of it", "Y UW1 S")],
    "excuse":    [("Verb", "excuse me", "IH0 K S K Y UW1 Z"), ("Noun", "an excuse", "IH0 K S K Y UW1 S")],
    "abuse":     [("Verb", "to abuse", "AH0 B Y UW1 Z"), ("Noun", "the abuse", "AH0 B Y UW1 S")],
    "house":     [("Noun", "a house", "HH AW1 S"), ("Verb", "to house someone", "HH AW1 Z")],
    "minute":    [("Noun", "sixty seconds", "M IH1 N AH0 T"), ("Adjective", "tiny", "M AY0 N UW1 T")],
    "separate":  [("Verb", "to separate them", "S EH1 P ER0 EY2 T"), ("Adjective", "separate rooms", "S EH1 P R AH0 T")],
    "estimate":  [("Verb", "to estimate", "EH1 S T AH0 M EY2 T"), ("Noun", "an estimate", "EH1 S T AH0 M AH0 T")],
    "graduate":  [("Verb", "to graduate", "G R AE1 JH UW0 EY2 T"), ("Noun", "a graduate", "G R AE1 JH UW0 AH0 T")],
    "alternate": [("Verb", "to alternate", "AO1 L T ER0 N EY2 T"), ("Adjective / Noun", "an alternate route", "AO1 L T ER0 N AH0 T")],
    "moderate":  [("Verb", "to moderate", "M AA1 D ER0 EY2 T"), ("Adjective", "moderate heat", "M AA1 D ER0 AH0 T")],
    "advocate":  [("Verb", "to advocate", "AE1 D V AH0 K EY2 T"), ("Noun", "an advocate", "AE1 D V AH0 K AH0 T")],
    "associate": [("Verb", "to associate", "AH0 S OW1 S IY0 EY2 T"), ("Noun", "a business associate", "AH0 S OW1 S IY0 AH0 T")],
    "delegate":  [("Verb", "to delegate", "D EH1 L AH0 G EY2 T"), ("Noun", "a delegate", "D EH1 L AH0 G AH0 T")],
    "elaborate": [("Verb", "to elaborate", "IH0 L AE1 B ER0 EY2 T"), ("Adjective", "an elaborate plan", "IH0 L AE1 B ER0 AH0 T")],
    "deliberate": [("Verb", "to deliberate", "D IH0 L IH1 B ER0 EY2 T"), ("Adjective", "a deliberate choice", "D IH0 L IH1 B ER0 AH0 T")],
    "duplicate": [("Verb", "to duplicate", "D UW1 P L AH0 K EY2 T"), ("Noun / Adjective", "a duplicate", "D UW1 P L AH0 K AH0 T")],
    "intimate":  [("Verb", "to hint at", "IH1 N T AH0 M EY2 T"), ("Adjective", "an intimate dinner", "IH1 N T AH0 M AH0 T")],
    "appropriate": [("Verb", "to take for oneself", "AH0 P R OW1 P R IY0 EY2 T"), ("Adjective", "appropriate behavior", "AH0 P R OW1 P R IY0 AH0 T")],
    "articulate": [("Verb", "to articulate", "AA0 R T IH1 K Y AH0 L EY2 T"), ("Adjective", "an articulate speaker", "AA0 R T IH1 K Y AH0 L AH0 T")],
    "approximate": [("Verb", "to approximate", "AH0 P R AA1 K S AH0 M EY2 T"), ("Adjective", "an approximate figure", "AH0 P R AA1 K S AH0 M AH0 T")],
    "coordinate": [("Verb", "to coordinate", "K OW0 AO1 R D AH0 N EY2 T"), ("Noun", "a coordinate", "K OW0 AO1 R D AH0 N AH0 T")],
    "attribute": [("Verb", "to attribute", "AH0 T R IH1 B Y UW0 T"), ("Noun", "an attribute", "AE1 T R AH0 B Y UW2 T")],
    "polish":    [("Verb / Noun", "to polish; shoe polish", "P AA1 L IH0 SH"), ("Adjective", "from Poland", "P OW1 L IH0 SH")],
    "resume":    [("Verb", "to continue", "R IH0 Z UW1 M"), ("Noun", "a CV / résumé", "R EH1 Z AH0 M EY2")],
    "learned":   [("Past tense", "I learned it", "L ER1 N D"), ("Adjective", "a learned scholar", "L ER1 N IH0 D")],
    "blessed":   [("Past tense", "he blessed them", "B L EH1 S T"), ("Adjective", "blessed are the meek", "B L EH1 S IH0 D")],
    "primer":    [("Noun", "a first coat of paint", "P R AY1 M ER0"), ("Noun", "an introductory book", "P R IH1 M ER0")],
    "does":      [("Verb", "she does", "D AH1 Z"), ("Noun", "female deer (plural)", "D OW1 Z")],
    "mobile":    [("Adjective", "able to move", "M OW1 B AH0 L"), ("Noun", "a hanging sculpture", "M OW1 B IY0 L")],
    "number":    [("Noun", "a number", "N AH1 M B ER0"), ("Adjective", "more numb", "N AH1 M ER0")],
    "putting":   [("Verb", "putting it down", "P UH1 T IH0 NG"), ("Verb", "putting in golf", "P AH1 T IH0 NG")],
    "buffet":    [("Noun", "a spread of food", "B AH0 F EY1"), ("Verb", "to strike repeatedly", "B AH1 F AH0 T")],
}


def _primary_stress_syllable(phones: List[str]) -> int:
    vi = [p for p in phones if strip_stress(p) in VOWEL_ARPA]
    for n, p in enumerate(vi):
        if p.endswith("1"):
            return n
    return -1


def heteronym_variants(word: str) -> List[Dict]:
    """Return [] or two+ {label, gloss, arpabet, ipa, categories} entries for
    words whose pronunciation depends on part of speech."""
    w = word.lower().strip()
    out: List[Dict] = []
    if w in _MANUAL_HETERONYMS:
        for label, gloss, arp in _MANUAL_HETERONYMS[w]:
            phones = arp.split()
            out.append({"label": label, "gloss": gloss, "arpabet": phones,
                        "ipa": arpabet_to_ipa(phones), "categories": classify_word(phones)})
        return out
    if w not in _STRESS_SHIFT_WORDS:
        return []
    first = next((v for v in cmu_variants(w) if _primary_stress_syllable(v) == 0), None)
    second = next((v for v in cmu_variants(w) if _primary_stress_syllable(v) == 1), None)
    if not first or not second:
        return []
    return [
        {"label": _FIRST_STRESS_LABEL.get(w, "Noun"), "gloss": "stress on the 1st syllable",
         "arpabet": first, "ipa": arpabet_to_ipa(first), "categories": classify_word(first)},
        {"label": "Verb", "gloss": "stress on the 2nd syllable",
         "arpabet": second, "ipa": arpabet_to_ipa(second), "categories": classify_word(second)},
    ]


def arpabet_to_ipa(phones: List[str]) -> str:
    """Convert an ARPABET phone list to dictionary-style American IPA.

    Cambridge conventions: syllables separated by "·", stress marks (ˈ / ˌ)
    placed before the onset of the stressed syllable and doubling as the
    boundary there, no stress mark on monosyllables. ER1/ER2 -> ɝ (stressed,
    "sERver"), ER0 -> ɚ (unstressed schwa + r-coloring, "servER"), AH0 -> ə.
    """
    syllables = syllabify(phones)
    if not syllables:
        return ""
    multi = len(syllables) > 1
    parts: List[str] = []
    for i, syl in enumerate(syllables):
        stress = ""
        text = ""
        for p in syl:
            m = re.match(r"^([A-Z]+)(\d?)$", p)
            if not m:
                continue
            base, s = m.group(1), m.group(2)
            if base in VOWEL_ARPA:
                stress = s
            if base == "AH" and s == "0":
                text += "ə"
            elif base == "ER" and s == "0":
                text += "ɚ"
            else:
                text += ARPA_TO_IPA.get(base, "")
        mark = ""
        if multi and stress == "1":
            mark = "ˈ"
        elif multi and stress == "2":
            mark = "ˌ"
        if i > 0 and not mark:
            mark = "·"
        parts.append(mark + text)
    return "".join(parts)


_LAX_VOWELS = {"IH", "EH", "AE", "AH", "UH"}
_ONSETS = {
    ("P", "R"), ("P", "L"), ("B", "R"), ("B", "L"), ("T", "R"), ("T", "W"),
    ("D", "R"), ("D", "W"), ("K", "R"), ("K", "L"), ("K", "W"), ("G", "R"),
    ("G", "L"), ("G", "W"), ("F", "R"), ("F", "L"), ("TH", "R"), ("TH", "W"),
    ("SH", "R"), ("S", "P"), ("S", "T"), ("S", "K"), ("S", "M"), ("S", "N"),
    ("S", "L"), ("S", "W"), ("S", "F"), ("HH", "Y"), ("K", "Y"), ("P", "Y"),
    ("B", "Y"), ("F", "Y"), ("M", "Y"), ("V", "Y"), ("N", "Y"), ("T", "Y"),
    ("D", "Y"), ("L", "Y"), ("G", "Y"),
    ("S", "P", "R"), ("S", "P", "L"), ("S", "T", "R"), ("S", "K", "R"),
    ("S", "K", "W"), ("S", "K", "L"), ("S", "P", "Y"), ("S", "K", "Y"),
}


def _is_onset(cluster: List[str]) -> bool:
    return len(cluster) == 1 or tuple(cluster) in _ONSETS


def syllabify(phones: List[str]) -> List[List[str]]:
    """Split ARPABET phones into syllables the way learner dictionaries do.

    Between two vowels the longest cluster that can begin an English syllable
    goes to the next syllable, except that a stressed lax vowel (ɪ ɛ æ ʌ ʊ)
    keeps at least one consonant as its coda ("hap·py", "mas·ter").
    """
    vowel_idx = [i for i, p in enumerate(phones) if strip_stress(p) in VOWEL_ARPA]
    if not vowel_idx:
        return [list(phones)] if phones else []
    syllables: List[List[str]] = []
    start = 0
    for n, vi in enumerate(vowel_idx):
        if n + 1 >= len(vowel_idx):
            syllables.append(list(phones[start:]))
            break
        cluster = list(phones[vi + 1:vowel_idx[n + 1]])
        v = phones[vi]
        lax_stressed = strip_stress(v) in _LAX_VOWELS and not v.endswith("0")
        split = 0
        for k in range(len(cluster) + 1):
            if not cluster[k:] or _is_onset(cluster[k:]):
                split = k
                break
        if lax_stressed and cluster and split == 0:
            split = 1
        syllables.append(list(phones[start:vi + 1 + split]))
        start = vi + 1 + split
    return syllables


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


def _r_colored(bare: List[str], i: int) -> bool:
    """True when vowel at index i is r-colored: followed by ER, or by a
    syllable-closing R (R not followed by a vowel). 'star', 'for', 'fire'
    -> True; 'very', 'sorry', 'Mary' -> False."""
    if i + 1 >= len(bare):
        return False
    nxt = bare[i + 1]
    if nxt == "ER":
        return True
    if nxt != "R":
        return False
    return i + 2 >= len(bare) or bare[i + 2] not in VOWEL_ARPA


def classify_word(phones: List[str]) -> List[str]:
    """Return the list of sound-category ids a word belongs to."""
    if not phones:
        return []
    cats: set = set()
    bare_all = [strip_stress(p) for p in phones]
    for i, p in enumerate(phones):
        bare = bare_all[i]
        if bare in ("R", "ER"):
            cats.add("rhotic_r")
        elif bare in VOWEL_ARPA and _r_colored(bare_all, i):
            cats.add("rhotic_r")
        elif bare == "AH":
            cats.add("v_schwa" if p.endswith("0") else "v_uh_stressed")
        elif bare in _ARPA_CATEGORY:
            cats.add(_ARPA_CATEGORY[bare])
    return [c for c in _CATEGORY_ORDER if c in cats]


_IPA_VOWEL_UNITS = ["eɪ", "aɪ", "oʊ", "aʊ", "ɔɪ", "i", "ɪ", "ɛ", "æ", "ə", "ʌ", "u", "ʊ", "ɔ", "ɑ", "a", "e", "o"]
_IPA_R_VOWELS = {"ɝ", "ɚ"}
_IPA_R_CONS = {"ɹ", "r"}
_IPA_MARKS = "ˈˌːˑ.·̩̃"


def _ipa_units(ipa: str) -> List[str]:
    units: List[str] = []
    i = 0
    while i < len(ipa):
        if ipa[i] in _IPA_MARKS:
            i += 1
            continue
        for v in _IPA_VOWEL_UNITS:
            if ipa.startswith(v, i):
                units.append(v)
                i += len(v)
                break
        else:
            units.append(ipa[i])
            i += 1
    return units


def _is_ipa_vowel(u: str) -> bool:
    return u in _IPA_VOWEL_UNITS or u in _IPA_R_VOWELS


def classify_ipa(ipa: Optional[str]) -> List[str]:
    """Best-effort categories from an IPA string (LLM fallback words)."""
    if not ipa:
        return []
    units = _ipa_units(ipa)
    cats: set = set()
    lookup = dict(_IPA_CATEGORY)
    for i, u in enumerate(units):
        if u in _IPA_R_VOWELS or u in _IPA_R_CONS:
            cats.add("rhotic_r")
            continue
        if u in _IPA_VOWEL_UNITS and i + 1 < len(units):
            nxt = units[i + 1]
            closes = nxt in _IPA_R_VOWELS or (
                nxt in _IPA_R_CONS and (i + 2 >= len(units) or not _is_ipa_vowel(units[i + 2]))
            )
            if closes:
                cats.add("rhotic_r")
                continue
        if u in lookup:
            cats.add(lookup[u])
    return [c for c in _CATEGORY_ORDER if c in cats]


def transcribe_word(word: str) -> Tuple[Optional[str], List[str], List[str]]:
    """Return (ipa, arpabet_phones, sound_categories) for a single word.

    Returns (None, [], []) if the word is not in the CMU dictionary; the caller
    can then fall back to an LLM-based transcription.
    """
    phones = get_arpabet(word)
    custom = CUSTOM_IPA.get((word or "").lower().strip())
    if custom:
        return custom, phones or [], classify_ipa(custom)
    if not phones:
        return None, [], []
    return arpabet_to_ipa(phones), phones, classify_word(phones)


# Coach-typed IPA (word -> IPA string) from the Admin "My Dictionary"
# builder. Wins over CMU for display + categories; loaded at startup.
CUSTOM_IPA: dict = {}

_CMU_WORDS: List[str] = []


def cmu_word_list() -> List[str]:
    """Sorted, de-duplicated CMU headwords (letters/apostrophes only)."""
    global _CMU_WORDS
    if not _CMU_WORDS:
        pronouncing.init_cmu()
        _CMU_WORDS = sorted({w for w, _ in pronouncing.pronunciations
                             if re.fullmatch(r"[a-z][a-z']*", w)})
    return _CMU_WORDS


_CMU_BY_FREQ: List[str] = []


def cmu_words_by_frequency() -> List[str]:
    """CMU headwords, most common English words first (wordfreq Zipf),
    ties and never-seen words alphabetical at the back."""
    global _CMU_BY_FREQ
    if not _CMU_BY_FREQ:
        from wordfreq import zipf_frequency
        words = cmu_word_list()
        _CMU_BY_FREQ = sorted(words, key=lambda w: (-zipf_frequency(w, "en"), w))
    return _CMU_BY_FREQ


def cmu_ipa(word: str) -> Optional[str]:
    phones = get_arpabet(word)
    return arpabet_to_ipa(phones) if phones else None
