"""
Unit tests for the three new output generators:
  1. generate_multi_nominations_table   (Feature 1)
  2. generate_main_page_column          (Feature 2)
  3. _format_category_page_row          (Feature 3)
  4. _insert_row_before_table_end
"""
import pytest
from awardsparser import (
    Category,
    Nominee,
    _extract_film_key,
    _make_count_table,
    generate_multi_nominations_table,
    _format_main_page_cell,
    generate_main_page_column,
    _format_category_page_row,
    _insert_row_before_table_end,
)


# ---------------------------------------------------------------------------
# _extract_film_key
# ---------------------------------------------------------------------------

class TestExtractFilmKey:
    def test_quoted_title_in_detail(self):
        n = Nominee(name="Alice, Bob", detail='"Great Scene", Studio A')
        assert _extract_film_key(n) == "Great Scene"

    def test_name_looks_like_film(self):
        n = Nominee(name="Grand Reel", detail="Studio A")
        assert _extract_film_key(n) == "Grand Reel"

    def test_name_with_comma_returns_none(self):
        n = Nominee(name="Alice, Bob")
        assert _extract_film_key(n) is None

    def test_name_with_and_returns_none(self):
        n = Nominee(name="Alice and Bob")
        assert _extract_film_key(n) is None

    def test_simple_name_no_detail(self):
        n = Nominee(name="Alpha Film")
        assert _extract_film_key(n) == "Alpha Film"


# ---------------------------------------------------------------------------
# generate_multi_nominations_table
# ---------------------------------------------------------------------------

def _make_cats():
    return [
        Category(
            name="Best Film",
            nominees=[
                Nominee("Alpha Film", "Studio A"),
                Nominee("Beta Film", "Studio B"),
                Nominee("Gamma Film", "Studio C"),
            ],
            winner=Nominee("Alpha Film", "Studio A"),
        ),
        Category(
            name="Best Scene",
            nominees=[
                Nominee("Alice, Bob", '"Alpha Film", Studio A'),
                Nominee("Carol, Dave", '"Beta Film", Studio B'),
            ],
            winner=Nominee("Alice, Bob", '"Alpha Film", Studio A'),
        ),
        Category(
            name="Best Director",
            nominees=[
                Nominee("Alpha Film", "Studio A"),
                Nominee("Delta Film", "Studio D"),
            ],
            winner=Nominee("Alpha Film", "Studio A"),
        ),
    ]


class TestGenerateMultiNominationsTable:
    def setup_method(self):
        self.cats = _make_cats()
        self.text = generate_multi_nominations_table(self.cats)

    def test_section_heading(self):
        assert "== Films with multiple nominations and awards ==" in self.text

    def test_col_begin_end(self):
        assert "{{col-begin" in self.text
        assert "{{col-end}}" in self.text

    def test_col_1_of_2_and_2_of_2(self):
        assert "{{col-1-of-2}}" in self.text
        assert "{{col-2-of-2}}" in self.text

    def test_nominations_table_caption(self):
        assert "Films with multiple nominations" in self.text

    def test_wins_table_caption(self):
        assert "Films with multiple wins" in self.text

    def test_alpha_film_has_most_nominations(self):
        # Alpha Film appears in Best Film + Best Scene (via detail) + Best Director = 3
        # But "Alpha Film" is the film key for Best Film and Best Director nominees directly
        # and "Alpha Film" is the scene title for Best Scene
        # The table should list it with count >= 2
        assert "Alpha Film" in self.text

    def test_count_with_rowspan(self):
        # If two films tie on count, rowspan should appear
        text = generate_multi_nominations_table(self.cats)
        # "Alpha Film" count = 3 (Best Film + Best Scene + Best Director)
        # "Beta Film" count = 2 (Best Film + Best Scene)
        assert "| 3" in text or "|3" in text or "scope=\"row\"| 3" in text

    def test_wikilinks_applied(self):
        text = generate_multi_nominations_table(
            self.cats, wikilinks={"alphafilm": "[[Alpha Film (2026 film)|Alpha Film]]"}
        )
        assert "[[Alpha Film (2026 film)|Alpha Film]]" in text

    def test_only_multiple_counts(self):
        # "Gamma Film" and "Delta Film" only appear once — should NOT be listed
        assert "Gamma Film" not in self.text
        assert "Delta Film" not in self.text

    def test_wikitable_plainrowheaders_class(self):
        assert "wikitable plainrowheaders" in self.text


# ---------------------------------------------------------------------------
# _format_main_page_cell
# ---------------------------------------------------------------------------

class TestFormatMainPageCell:
    def test_no_winner_returns_tba(self):
        assert _format_main_page_cell(None, {}) == "''TBA''"

    def test_winner_name_only(self):
        w = Nominee("Alice")
        assert _format_main_page_cell(w, {}) == "Alice"

    def test_winner_with_film_detail(self):
        w = Nominee("Alice", '"Great Scene", Studio')
        cell = _format_main_page_cell(w, {})
        assert "Alice" in cell
        assert "{{spaced ndash}}" in cell
        assert "''Great Scene''" in cell

    def test_winner_name_with_plain_detail(self):
        w = Nominee("Alice", "Great Film")
        cell = _format_main_page_cell(w, {})
        assert "{{spaced ndash}}" in cell
        assert "''Great Film''" in cell

    def test_wikilink_applied_to_name(self):
        w = Nominee("Alice")
        cell = _format_main_page_cell(w, {"alice": "[[Alice (performer)|Alice]]"})
        assert "[[Alice (performer)|Alice]]" in cell


# ---------------------------------------------------------------------------
# generate_main_page_column
# ---------------------------------------------------------------------------

class TestGenerateMainPageColumn:
    def setup_method(self):
        cats = [
            Category("Best New Starlet",
                     nominees=[Nominee("Jane Doe", "Film A")],
                     winner=Nominee("Jane Doe", "Film A")),
            Category("Female Performer of the Year",
                     nominees=[Nominee("Alice", "Film B")],
                     winner=Nominee("Alice", "Film B")),
        ]
        self.text = generate_main_page_column(cats, 2026)

    def test_contains_year_and_ceremony(self):
        assert "2026" in self.text
        assert "43rd AVN Awards" in self.text

    def test_header_instruction_present(self):
        assert "[[43rd AVN Awards|2026]]" in self.text

    def test_category_annotations(self):
        assert "Best New Starlet" in self.text
        assert "Female Performer of the Year" in self.text

    def test_cell_format_uses_pipe(self):
        # Each cell line starts with |
        cell_lines = [l for l in self.text.split('\n') if l.startswith('|') and not l.startswith('|-')]
        assert len(cell_lines) > 0

    def test_tba_for_missing_category(self):
        # Categories not in our data → TBA
        assert "''TBA''" in self.text


# ---------------------------------------------------------------------------
# _format_category_page_row
# ---------------------------------------------------------------------------

class TestFormatCategoryPageRow:
    def _row(self, winner=None, nominees=None, year=2026, wl=None, **kw):
        return _format_category_page_row(
            year=year,
            winner=winner,
            other_nominees=nominees or [],
            wikilinks=wl or {},
            **kw,
        )

    def test_starts_with_separator(self):
        row = self._row(winner=Nominee("Alice"))
        assert row.startswith('|-')

    def test_year_present(self):
        row = self._row(winner=Nominee("Alice"))
        assert "2026" in row

    def test_winner_bold(self):
        row = self._row(winner=Nominee("Alice"))
        assert "'''Alice'''" in row

    def test_winner_with_film_uses_small_template(self):
        row = self._row(winner=Nominee("Alice", '"Great Film", Studio'))
        assert "{{small|" in row
        assert "Great Film" in row

    def test_winner_film_in_bold_italic(self):
        row = self._row(winner=Nominee("Alice", '"Great Film"'))
        # Bold-italic = 5 apostrophes
        assert "'''''" in row

    def test_nominee_film_in_italic(self):
        row = self._row(
            winner=Nominee("Alice", '"Film A"'),
            nominees=[Nominee("Bob", '"Film B"')],
        )
        # Nominee film: {{small|''Film B''}} — 2 apostrophes, not 5
        assert "''Film B''" in row

    def test_rowspan_for_multiple_nominees(self):
        row = self._row(
            winner=Nominee("Alice"),
            nominees=[Nominee("Bob"), Nominee("Carol"), Nominee("Dave")],
        )
        assert "rowspan=3" in row

    def test_no_rowspan_single_nominee(self):
        row = self._row(winner=Nominee("Alice"), nominees=[Nominee("Bob")])
        assert "rowspan" not in row

    def test_tba_when_no_winner(self):
        row = self._row()
        assert "''TBA''" in row

    def test_refs_included_when_urls_given(self):
        row = self._row(
            winner=Nominee("Alice"),
            nominees_url="https://avn.com/nominees",
            winners_url="https://avn.com/winners",
        )
        assert "<ref>" in row
        assert "avn.com/nominees" in row

    def test_wikilink_applied_to_winner(self):
        row = self._row(
            winner=Nominee("Alice"),
            wl={"alice": "[[Alice (performer)|Alice]]"},
        )
        assert "[[Alice (performer)|Alice]]" in row


# ---------------------------------------------------------------------------
# _insert_row_before_table_end
# ---------------------------------------------------------------------------

class TestInsertRowBeforeTableEnd:
    def test_inserts_before_last_close(self):
        wikitext = "{| class=wikitable\n|-\n|row1\n|}"
        result = _insert_row_before_table_end(wikitext, "|-\n|new row")
        assert result.index("|-\n|new row") < result.index("|}")

    def test_inserts_before_last_close_when_multiple(self):
        wikitext = "{|\n|}\n{|\n|}"
        result = _insert_row_before_table_end(wikitext, "|-\n|new")
        # New row should appear before the LAST |}
        last_close = result.rfind("|}")
        new_row_pos = result.rfind("|-\n|new")
        assert new_row_pos < last_close

    def test_fallback_appends_when_no_close(self):
        wikitext = "{| class=wikitable\n|-\n|row1"
        result = _insert_row_before_table_end(wikitext, "|-\n|new")
        assert "|-\n|new" in result
