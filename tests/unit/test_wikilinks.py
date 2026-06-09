"""Unit tests for wikilink extraction and validation."""
import sys
import pytest

from awardsparser import extract_wikilinks, validate_wikipedia_article, _apply_wikilink


class TestExtractWikilinks:
    def test_simple_link(self):
        links = extract_wikilinks("Some text [[Tommy Pistol]] more text")
        assert links.get("tommypistol") == "[[Tommy Pistol]]"

    def test_piped_link_uses_display_text_as_key(self):
        links = extract_wikilinks("[[Tommy Pistol (actor)|Tommy Pistol]]")
        # Key is the display text, value preserves the full markup
        assert links.get("tommypistol") == "[[Tommy Pistol (actor)|Tommy Pistol]]"

    def test_piped_link_preserves_full_markup(self):
        links = extract_wikilinks("[[Digital Playground|Digital Playground]]")
        assert "[[Digital Playground" in links.get("digitalplayground", "")

    def test_skips_file_namespace(self):
        links = extract_wikilinks("[[File:image.png|thumb|Caption]]")
        assert len(links) == 0

    def test_skips_category_namespace(self):
        links = extract_wikilinks("[[Category:AVN Award winners]]")
        assert len(links) == 0

    def test_skips_template_namespace(self):
        links = extract_wikilinks("[[Template:Infobox]]")
        assert len(links) == 0

    def test_first_occurrence_wins_on_duplicate_display(self):
        # Same display text, different targets — first one should be kept
        wikitext = "[[Article A|Tommy]] ... [[Article B|Tommy]]"
        links = extract_wikilinks(wikitext)
        assert links.get("tommy") == "[[Article A|Tommy]]"

    def test_multiple_links(self):
        wikitext = "[[Tommy Pistol]] won, [[Anna Claire Clouds]] was nominated"
        links = extract_wikilinks(wikitext)
        assert "tommypistol" in links
        assert "annaclaireclouds" in links

    def test_empty_wikitext(self):
        assert extract_wikilinks("") == {}

    def test_no_partial_match(self):
        # "Digital Playground/Pulse" should NOT match [[Digital Playground]]
        links = extract_wikilinks("[[Digital Playground]]")
        key = "digitalplaygroundpulse"
        assert key not in links


class TestApplyWikilink:
    def test_matching_name_is_replaced(self):
        links = {"tommypistol": "[[Tommy Pistol]]"}
        assert _apply_wikilink("Tommy Pistol", links) == "[[Tommy Pistol]]"

    def test_non_matching_name_unchanged(self):
        links = {"tommypistol": "[[Tommy Pistol]]"}
        assert _apply_wikilink("Chad White", links) == "Chad White"

    def test_empty_links_dict(self):
        assert _apply_wikilink("Tommy Pistol", {}) == "Tommy Pistol"

    def test_no_partial_match(self):
        # "Digital Playground/Pulse" must not pick up [[Digital Playground]]
        links = {"digitalplayground": "[[Digital Playground]]"}
        assert _apply_wikilink("Digital Playground/Pulse", links) == "Digital Playground/Pulse"

    # ------------------------------------------------------------------
    # Multi-performer splitting (Fix: group scene entries)
    # ------------------------------------------------------------------

    def test_multi_performer_comma_separated(self):
        links = {
            "alice": "[[Alice]]",
            "bob": "[[Bob]]",
        }
        result = _apply_wikilink("Alice, Bob, Carol", links)
        assert "[[Alice]]" in result
        assert "[[Bob]]" in result
        assert "Carol" in result  # unlinked name preserved as-is

    def test_multi_performer_ampersand_separator(self):
        links = {"alice": "[[Alice]]", "bob": "[[Bob]]"}
        result = _apply_wikilink("Alice & Bob", links)
        assert "[[Alice]]" in result
        assert "[[Bob]]" in result

    def test_multi_performer_mixed_separators(self):
        links = {
            "jenniferwhite": "[[Jennifer White (actress)|Jennifer White]]",
            "annaclaireclouds": "[[Anna Claire Clouds]]",
            "jewelzblu": "[[Jewelz Blu]]",
        }
        result = _apply_wikilink(
            "Jennifer White, Anna Claire Clouds, Blake Blossom & Jewelz Blu", links)
        assert "[[Jennifer White (actress)|Jennifer White]]" in result
        assert "[[Anna Claire Clouds]]" in result
        assert "Blake Blossom" in result   # no link — kept plain
        assert "[[Jewelz Blu]]" in result

    def test_multi_performer_no_links_returns_unchanged(self):
        links = {"unrelated": "[[Unrelated]]"}
        original = "Alice, Bob & Carol"
        assert _apply_wikilink(original, links) == original

    def test_single_name_without_separators_unchanged_when_no_match(self):
        # Should not attempt splitting for a name with no , or &
        links = {"alice": "[[Alice]]"}
        assert _apply_wikilink("Bob", links) == "Bob"


class TestValidateWikipediaArticle:
    def test_passes_when_year_present(self):
        # Should not raise or exit
        validate_wikipedia_article("The 43rd AVN Awards ceremony in 2026...", 2026, "43rd AVN Awards")

    def test_exits_when_year_absent(self):
        with pytest.raises(SystemExit):
            validate_wikipedia_article("The 43rd AVN Awards ceremony...", 2030, "43rd AVN Awards")
