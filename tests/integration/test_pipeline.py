"""
Integration tests for the full parse → merge → generate pipeline.

These tests use local HTML fixtures so they run without network access
or a browser. fetch_html is never called.
"""
import os
import pytest

from awardsparser import (
    parse_nominees_page,
    parse_winners_page,
    merge_winners,
    generate_wikitext,
    extract_wikilinks,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(filename: str) -> str:
    with open(os.path.join(FIXTURES, filename), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Nominees page parsing
# ---------------------------------------------------------------------------

class TestParseNomineesPage:
    def setup_method(self):
        self.html = load("nominees.html")
        self.cats = parse_nominees_page(self.html)

    def test_finds_expected_categories(self):
        names = [c.name for c in self.cats]
        assert "Grand Reel" in names
        assert "Best Boy/Girl Sex Scene" in names
        assert "Best Male Newcomer" in names

    def test_section_header_not_parsed_as_category(self):
        names = [c.name for c in self.cats]
        assert "VIDEO" not in names
        assert "FAN-VOTED WINNERS" not in names

    def test_section_assigned_to_categories(self):
        fan_cats = [c for c in self.cats if c.section == "Fan-Voted Winners"]
        assert len(fan_cats) >= 1
        assert fan_cats[0].name == "Favorite Female Porn Star"

    def test_film_category_strong_separated(self):
        cat = next(c for c in self.cats if c.name == "Grand Reel")
        assert len(cat.nominees) == 3
        assert cat.nominees[0].name == "Alpha Film"
        assert cat.nominees[1].name == "Beta Film"

    def test_scene_category_with_performers(self):
        cat = next(c for c in self.cats if c.name == "Best Boy/Girl Sex Scene")
        assert len(cat.nominees) == 2
        assert "Alice" in cat.nominees[0].name

    def test_br_separated_nominees(self):
        cat = next(c for c in self.cats if c.name == "Best Male Newcomer")
        assert len(cat.nominees) == 4
        names = [n.name for n in cat.nominees]
        assert "Nominee Alpha" in names
        assert "Nominee Delta" in names

    def test_no_winner_before_merge(self):
        for cat in self.cats:
            assert cat.winner is None


# ---------------------------------------------------------------------------
# Winners page parsing
# ---------------------------------------------------------------------------

class TestParseWinnersPage:
    def setup_method(self):
        self.html = load("winners.html")
        self.cats = parse_winners_page(self.html)

    def test_finds_expected_categories(self):
        names = [c.name for c in self.cats]
        assert "Grand Reel" in names
        assert "Best Boy/Girl Sex Scene" in names

    def test_winner_parsed_for_film_category(self):
        cat = next(c for c in self.cats if c.name == "Grand Reel")
        assert cat.winner is not None
        assert cat.winner.name == "Alpha Film"

    def test_winner_parsed_for_scene_category(self):
        cat = next(c for c in self.cats if c.name == "Best Boy/Girl Sex Scene")
        assert cat.winner is not None
        assert "Alice" in cat.winner.name or "Scene One" in cat.winner.detail

    def test_section_assigned_correctly(self):
        cat = next(c for c in self.cats if c.name == "Favorite Female Porn Star")
        assert cat.section == "Fan-Voted Winners"

    def test_category_without_winner_when_next_is_also_label(self):
        # "Best Male Newcomer" has no winner line — next para is another label
        cat = next((c for c in self.cats if c.name == "Best Male Newcomer"), None)
        assert cat is not None
        assert cat.winner is None

    def test_section_header_not_parsed_as_category(self):
        names = [c.name for c in self.cats]
        assert "FAN-VOTED WINNERS" not in names


# ---------------------------------------------------------------------------
# Merge winners into nominees
# ---------------------------------------------------------------------------

class TestMergePipeline:
    def setup_method(self):
        nominees_html = load("nominees.html")
        winners_html = load("winners.html")
        self.cats = parse_nominees_page(nominees_html)
        winner_cats = parse_winners_page(winners_html)
        merge_winners(self.cats, winner_cats)

    def test_winner_merged_into_nominees(self):
        cat = next(c for c in self.cats if c.name == "Grand Reel")
        assert cat.winner is not None
        assert cat.winner.name == "Alpha Film"

    def test_winner_present_in_nominees_list(self):
        cat = next(c for c in self.cats if c.name == "Grand Reel")
        # The winner entry should already be in the nominees list from parsing
        assert any(n.name == "Alpha Film" for n in cat.nominees)

    def test_unmatched_categories_have_no_winner(self):
        cat = next((c for c in self.cats if c.name == "Best Male Newcomer"), None)
        if cat:
            # Best Male Newcomer has no winner in fixture
            assert cat.winner is None


# ---------------------------------------------------------------------------
# Full pipeline: parse → merge → generate
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def setup_method(self):
        nominees_html = load("nominees.html")
        winners_html = load("winners.html")
        self.cats = parse_nominees_page(nominees_html)
        winner_cats = parse_winners_page(winners_html)
        merge_winners(self.cats, winner_cats)
        self.wikitext = generate_wikitext(self.cats)

    def test_output_is_nonempty(self):
        assert len(self.wikitext) > 0

    def test_wikitable_structure_present(self):
        assert '{| class="wikitable"' in self.wikitext
        assert "|}" in self.wikitext

    def test_award_category_template_present(self):
        assert "{{Award category|#89cff0|Grand Reel}}" in self.wikitext

    def test_winner_is_bold(self):
        assert "'''Alpha Film'''" in self.wikitext

    def test_nominees_listed_under_winner(self):
        assert "** Beta Film" in self.wikitext

    def test_section_heading_present(self):
        assert "=== Fan-Voted Winners ===" in self.wikitext

    def test_em_dash_used_consistently(self):
        # Film entries should use em-dash between name and studio.
        # Winner is bold so it appears as '''Alpha Film''' – ''Studio One''
        assert "'''Alpha Film''' –" in self.wikitext
        # Non-winner nominee should also use em-dash
        assert "Beta Film –" in self.wikitext

    def test_wikilinks_applied_from_existing_article(self):
        wikitext_existing = load("existing_wiki.txt")
        links = extract_wikilinks(wikitext_existing)
        wikitext = generate_wikitext(self.cats, wikilinks=links)
        assert "[[Alpha Film]]" in wikitext
        assert "[[Beta Film]]" in wikitext

    def test_wikilinks_no_partial_match(self):
        # A link for "Studio One" must not bleed into "Studio One Extra"
        links = {"studioone": "[[Studio One]]"}
        wikitext = generate_wikitext(self.cats, wikilinks=links)
        # "Studio One Extra" (if present) should not become [[Studio One]] Extra
        assert "[[Studio One]] Extra" not in wikitext
