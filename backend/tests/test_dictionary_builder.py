"""Custom IPA from the Admin dictionary wins over CMU for display/categories."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import phonetics
from phonetics import transcribe_word, cmu_word_list, cmu_ipa


def test_cmu_word_list_is_sorted_clean():
    words = cmu_word_list()
    assert len(words) > 100_000
    assert words == sorted(words)
    assert all(w[0].isalpha() for w in words)


def test_custom_ipa_overrides_cmu(monkeypatch):
    monkeypatch.setitem(phonetics.CUSTOM_IPA, "because", "bɪˈkʌz")
    ipa, arpa, cats = transcribe_word("because")
    assert ipa == "bɪˈkʌz"
    assert arpa
    assert "v_uh_stressed" in cats and "v_ih" in cats


def test_custom_ipa_for_non_cmu_word(monkeypatch):
    custom = "hɝˈmaɪəni"
    monkeypatch.setitem(phonetics.CUSTOM_IPA, "hermionexx", custom)
    ipa, arpa, cats = transcribe_word("hermionexx")
    assert ipa == custom and arpa == []
    assert "rhotic_r" in cats and "d_ay" in cats


def test_cmu_ipa_none_for_unknown():
    assert cmu_ipa("zzzzqqq") is None


def test_frequency_order_puts_common_words_first():
    from phonetics import cmu_words_by_frequency
    words = cmu_words_by_frequency()
    assert words[0] == "the"
    assert words.index("because") < words.index("hermione") < words.index("aaberg")
    assert len(words) == len(cmu_word_list())
