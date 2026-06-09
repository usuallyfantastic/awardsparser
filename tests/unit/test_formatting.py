"""Unit tests for wikitext formatting and output generation."""
import pytest

from awardsparser import (
    Nominee, Category,
    _format_entry, _wiki_escape,
    generate_wikitext,
)


class TestWikiEscape:
    def test_pipe_becomes_template(self):
        assert _wiki_escape("A | B") == "A {{!}} B"

    def test_no_pipe_unchanged(self):
        assert _wiki_escape("Hello World") == "Hello World"


class TestFormatEntry:
    def test_name_only(self):
        n = Nominee(name="Axel Haze")
        assert _format_entry(n) == "Axel Haze"

    def test_bold_name(self):
        n = Nominee(name="Axel Haze")
        assert _format_entry(n, bold=True) == "'''Axel Haze'''"

    def test_name_with_plain_detail(self):
        n = Nominee(name="After Dark", detail="Dorcel/Pulse")
        result = _format_entry(n)
        assert result == "After Dark – ''Dorcel/Pulse''"

    def test_name_with_quoted_title_and_studio(self):
        n = Nominee(name="Tommy Pistol", detail='"Mr. Sicko and the Little Lady" | Sex and Submission/Kink')
        result = _format_entry(n)
        assert "Tommy Pistol" in result
        assert "–" in result
        assert "''\"Mr. Sicko and the Little Lady\"''" in result
        assert "Sex and Submission/Kink" in result

    def test_quoted_title_studio_uses_comma_not_pipe(self):
        # After formatting, the pipe separator between title and studio should
        # be replaced with ", " and the pipe itself must not appear literally.
        n = Nominee(name="Tommy Pistol", detail='"Scene" | Studio')
        result = _format_entry(n)
        # The raw " | " separator must not survive into the output
        assert " | " not in result
        # Studio should follow the title separated by a comma
        assert ", Studio" in result or ", {{!}} Studio" not in result

    def test_emdash_separator_normalised(self):
        n = Nominee(name="Tommy Pistol", detail='"Scene" – Studio')
        result = _format_entry(n)
        assert " – Studio" not in result  # the source separator should be gone
        assert ", Studio" in result

    def test_wikilink_applied_to_name(self):
        n = Nominee(name="Tommy Pistol", detail="Strip")
        links = {"tommypistol": "[[Tommy Pistol]]"}
        result = _format_entry(n, wikilinks=links)
        assert "[[Tommy Pistol]]" in result

    def test_wikilink_applied_to_detail(self):
        n = Nominee(name="After Dark", detail="Elegant Angel")
        links = {"elegantangel": "[[Elegant Angel]]"}
        result = _format_entry(n, wikilinks=links)
        assert "[[Elegant Angel]]" in result

    def test_no_partial_wikilink_match(self):
        # "Digital Playground/Pulse" must not get [[Digital Playground]] link
        n = Nominee(name="Ghosted", detail="Digital Playground/Pulse")
        links = {"digitalplayground": "[[Digital Playground]]"}
        result = _format_entry(n, wikilinks=links)
        assert "[[Digital Playground]]" not in result
        assert "Digital Playground/Pulse" in result

    def test_pipe_in_name_is_escaped(self):
        n = Nominee(name="A | B")
        assert "{{!}}" in _format_entry(n)


class TestGenerateWikitext:
    def _two_cats(self):
        return [
            Category(name="Best Actor", nominees=[Nominee("Alice"), Nominee("Bob")]),
            Category(name="Best Actress", nominees=[Nominee("Carol"), Nominee("Dana")]),
        ]

    def test_empty_categories(self):
        assert generate_wikitext([]) == "<!-- No categories found -->"

    def test_table_open_and_close(self):
        result = generate_wikitext(self._two_cats())
        assert '{| class="wikitable"' in result
        assert "|}" in result

    def test_two_categories_per_row(self):
        result = generate_wikitext(self._two_cats())
        # Both categories should appear within a single "|-" row block
        assert "Best Actor" in result
        assert "Best Actress" in result
        # Only one row separator for two categories
        assert result.count("|-") == 1

    def test_award_category_template(self):
        result = generate_wikitext(self._two_cats())
        assert "{{Award category|#89cff0|Best Actor}}" in result

    def test_nominees_listed_without_winners(self):
        result = generate_wikitext(self._two_cats())
        assert "* Alice" in result
        assert "* Bob" in result

    def test_winner_shown_bold_at_top(self):
        cats = [
            Category(
                name="Best Actor",
                nominees=[Nominee("Alice"), Nominee("Bob")],
                winner=Nominee("Alice"),
            )
        ]
        result = generate_wikitext(cats)
        assert "* '''Alice'''" in result
        assert "** Bob" in result

    def test_winner_not_duplicated_in_nominees(self):
        cats = [
            Category(
                name="Best Actor",
                nominees=[Nominee("Alice"), Nominee("Bob")],
                winner=Nominee("Alice"),
            )
        ]
        result = generate_wikitext(cats)
        # Alice should appear once as winner, not again as nominee
        assert result.count("Alice") == 1

    def test_tba_when_no_nominees_and_no_winners(self):
        cats = [Category(name="Best Actor", nominees=[])]
        result = generate_wikitext(cats)
        assert "''TBA''" in result

    def test_section_heading(self):
        cats = [
            Category(name="Best Toy", section="Pleasure Products",
                     nominees=[Nominee("Brand A")]),
        ]
        result = generate_wikitext(cats)
        assert "=== Pleasure Products ===" in result

    def test_vertical_align_top(self):
        result = generate_wikitext(self._two_cats())
        assert "vertical-align:top" in result

    def test_custom_header_color(self):
        result = generate_wikitext(self._two_cats(), header_color="#ff0000")
        assert "#ff0000" in result

    def test_wikilinks_applied_in_output(self):
        # Two nominees so has_nominees=True; a winner so winner path is taken
        cats = [Category(
            name="Best Actor",
            nominees=[Nominee("Tommy Pistol"), Nominee("Chad White")],
            winner=Nominee("Tommy Pistol"),
        )]
        links = {"tommypistol": "[[Tommy Pistol]]"}
        result = generate_wikitext(cats, wikilinks=links)
        assert "[[Tommy Pistol]]" in result

    def test_odd_number_of_categories(self):
        cats = [
            Category(name="Cat A", nominees=[Nominee("X")]),
            Category(name="Cat B", nominees=[Nominee("Y")]),
            Category(name="Cat C", nominees=[Nominee("Z")]),
        ]
        result = generate_wikitext(cats)
        # Two rows: (A,B) and (C,)
        assert result.count("|-") == 2
        assert "Cat C" in result
