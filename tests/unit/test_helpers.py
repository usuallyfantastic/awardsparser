"""Unit tests for shared helper functions."""
import pytest
from awardsparser import _clean, _normalize, _is_all_caps, _ordinal, _avn_wikipedia_title, _title_from_wikipedia_url


class TestClean:
    def test_strips_whitespace(self):
        assert _clean("  hello  ") == "hello"

    def test_collapses_internal_spaces(self):
        assert _clean("hello   world") == "hello world"

    def test_replaces_nbsp(self):
        assert _clean("hello\xa0world") == "hello world"

    def test_collapses_mixed_whitespace(self):
        assert _clean("a \t\n b") == "a b"

    def test_empty_string(self):
        assert _clean("") == ""


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello") == "hello"

    def test_strips_non_alphanumeric(self):
        assert _normalize("Digital Playground/Pulse") == "digitalplaygroundpulse"

    def test_strips_punctuation(self):
        assert _normalize("Best Boy/Girl Sex Scene") == "bestboygirlsexscene"

    def test_empty_string(self):
        assert _normalize("") == ""

    def test_numbers_preserved(self):
        assert _normalize("43rd AVN Awards") == "43rdavnawards"


class TestIsAllCaps:
    def test_all_caps_returns_true(self):
        assert _is_all_caps("PLEASURE PRODUCTS") is True

    def test_all_caps_single_word(self):
        assert _is_all_caps("RETAIL") is True

    def test_mixed_case_returns_false(self):
        assert _is_all_caps("Best Actor") is False

    def test_title_case_returns_false(self):
        assert _is_all_caps("Grand Reel") is False

    def test_too_few_letters_returns_false(self):
        # Only 2 letters — requires >= 3
        assert _is_all_caps("AB") is False

    def test_all_caps_with_numbers(self):
        # Numbers are ignored; letters must all be upper
        assert _is_all_caps("FAN-VOTED WINNERS") is True

    def test_lowercase_word_returns_false(self):
        assert _is_all_caps("BEST actor") is False


class TestOrdinal:
    @pytest.mark.parametrize("n,expected", [
        (1,  "1st"),
        (2,  "2nd"),
        (3,  "3rd"),
        (4,  "4th"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (22, "22nd"),
        (23, "23rd"),
        (43, "43rd"),
        (44, "44th"),
        (100, "100th"),
        (101, "101st"),
        (111, "111th"),
    ])
    def test_ordinal(self, n, expected):
        assert _ordinal(n) == expected


class TestAvnWikipediaTitle:
    def test_2026_is_43rd(self):
        assert _avn_wikipedia_title(2026) == "43rd AVN Awards"

    def test_2025_is_42nd(self):
        assert _avn_wikipedia_title(2025) == "42nd AVN Awards"

    def test_2027_is_44th(self):
        assert _avn_wikipedia_title(2027) == "44th AVN Awards"

    def test_2024_is_41st(self):
        assert _avn_wikipedia_title(2024) == "41st AVN Awards"


class TestTitleFromWikipediaUrl:
    def test_standard_url(self):
        url = "https://en.wikipedia.org/wiki/43rd_AVN_Awards"
        assert _title_from_wikipedia_url(url) == "43rd AVN Awards"

    def test_url_with_fragment(self):
        url = "https://en.wikipedia.org/wiki/43rd_AVN_Awards#Nominees"
        assert _title_from_wikipedia_url(url) == "43rd AVN Awards"

    def test_url_with_query(self):
        url = "https://en.wikipedia.org/wiki/43rd_AVN_Awards?action=edit"
        assert _title_from_wikipedia_url(url) == "43rd AVN Awards"

    def test_encoded_url(self):
        url = "https://en.wikipedia.org/wiki/98th_Academy_Awards"
        assert _title_from_wikipedia_url(url) == "98th Academy Awards"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Could not parse"):
            _title_from_wikipedia_url("https://en.wikipedia.org/")
