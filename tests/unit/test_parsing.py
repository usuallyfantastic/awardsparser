"""Unit tests for parsing helpers."""
import pytest
from bs4 import BeautifulSoup

from awardsparser import (
    Nominee, Category,
    _is_category_label,
    _parse_performer_and_title,
    _split_nominees_paragraph,
    _nominee_matches_winner,
    merge_winners,
)


def make_p(html: str) -> "Tag":
    return BeautifulSoup(html, "html.parser").find("p")


class TestIsCategoryLabel:
    def test_simple_strong(self):
        p = make_p("<p><strong>Best Actor</strong></p>")
        assert _is_category_label(p) is True

    def test_strong_with_underline(self):
        # AVN nominees page wraps some labels in <strong><u>
        p = make_p("<p><strong><u>Best Male Newcomer</u></strong></p>")
        assert _is_category_label(p) is True

    def test_plain_text_paragraph(self):
        p = make_p("<p>Some plain text here</p>")
        assert _is_category_label(p) is False

    def test_strong_is_only_part_of_text(self):
        # Strong covers only part of the paragraph text
        p = make_p("<p>Winner: <strong>Tommy Pistol</strong></p>")
        assert _is_category_label(p) is False

    def test_empty_paragraph(self):
        p = make_p("<p></p>")
        assert _is_category_label(p) is False


class TestParsePerformerAndTitle:
    def test_performer_with_quoted_title_and_pipe(self):
        n = _parse_performer_and_title('Chanel Camryn & Milan Ponjevic, "Midnight Movie" | If It Feels Good 5, Deeper/Pulse')
        assert n.name == "Chanel Camryn & Milan Ponjevic"
        assert '"Midnight Movie"' in n.detail

    def test_performer_with_quoted_title_no_studio(self):
        n = _parse_performer_and_title('Tommy Pistol, "Mr. Sicko and the Little Lady"')
        assert n.name == "Tommy Pistol"
        assert n.detail == '"Mr. Sicko and the Little Lady"'

    def test_title_only_no_performer(self):
        # No text before the quote — title becomes the name
        n = _parse_performer_and_title('"Midnight Movie" | Deeper/Pulse')
        assert '"Midnight Movie"' in n.name

    def test_pipe_separator(self):
        n = _parse_performer_and_title("Ghosted | Digital Playground/Pulse")
        assert n.name == "Ghosted"
        assert n.detail == "Digital Playground/Pulse"

    def test_emdash_separator(self):
        n = _parse_performer_and_title("Ghosted – Digital Playground/Pulse")
        assert n.name == "Ghosted"
        assert n.detail == "Digital Playground/Pulse"

    def test_hyphen_separator(self):
        n = _parse_performer_and_title("Ghosted - Digital Playground")
        assert n.name == "Ghosted"
        assert n.detail == "Digital Playground"

    def test_comma_separator_fallback(self):
        n = _parse_performer_and_title("After Dark, Dorcel/Pulse")
        assert n.name == "After Dark"
        assert n.detail == "Dorcel/Pulse"

    def test_no_separator(self):
        n = _parse_performer_and_title("Axel Haze")
        assert n.name == "Axel Haze"
        assert n.detail == ""

    def test_strips_leading_comma(self):
        n = _parse_performer_and_title(", Some Nominee, Studio")
        assert not n.name.startswith(",")

    def test_comma_splits_on_first_occurrence(self):
        # "Tommy Pistol, Strip, Dorcel/Pulse" → name="Tommy Pistol", detail="Strip, Dorcel/Pulse"
        n = _parse_performer_and_title("Tommy Pistol, Strip, Dorcel/Pulse")
        assert n.name == "Tommy Pistol"
        assert n.detail == "Strip, Dorcel/Pulse"


class TestSplitNomineesParagraph:
    def test_strong_separated(self):
        # In the AVN page pattern, the <strong> marks the scene/film title.
        # Performer text before the strong becomes the nominee's name; the
        # text between the closing strong and the next opening strong is
        # treated as trailing info (studio) for that entry.
        html = (
            "<p>Alice, <strong>\"Scene One\"</strong> | Studio A"
            "<strong>\"Scene Two\"</strong> | Studio B</p>"
        )
        p = make_p(html)
        nominees = _split_nominees_paragraph(p)
        assert len(nominees) == 2
        # First entry: performer "Alice" with scene title as detail
        assert "Alice" in nominees[0].name
        # Second entry: no preceding performer text, scene title becomes name
        assert "Scene Two" in nominees[1].name

    def test_br_separated(self):
        html = "<p>Name One<br/>Name Two<br/>Name Three</p>"
        p = make_p(html)
        nominees = _split_nominees_paragraph(p)
        assert len(nominees) == 3
        assert nominees[0].name == "Name One"
        assert nominees[1].name == "Name Two"
        assert nominees[2].name == "Name Three"

    def test_no_strong_single_nominee(self):
        html = "<p>Single Nominee, Studio</p>"
        p = make_p(html)
        nominees = _split_nominees_paragraph(p)
        assert len(nominees) == 1
        assert nominees[0].name == "Single Nominee"

    def test_film_only_strong_separated(self):
        # Movie categories: <strong>Film Title</strong> Studio text
        html = "<p><strong>Film A</strong>, Studio X<strong>Film B</strong>, Studio Y</p>"
        p = make_p(html)
        nominees = _split_nominees_paragraph(p)
        assert len(nominees) == 2
        assert nominees[0].name == "Film A"
        assert nominees[1].name == "Film B"

    def test_empty_paragraph(self):
        html = "<p>\xa0</p>"
        p = make_p(html)
        nominees = _split_nominees_paragraph(p)
        assert nominees == []


class TestNomineeMatchesWinner:
    def test_exact_name_match(self):
        w = Nominee(name="Tommy Pistol", detail="Strip")
        n = Nominee(name="Tommy Pistol", detail="Strip")
        assert _nominee_matches_winner(n, w) is True

    def test_scene_title_as_name(self):
        # Nominee is stored as just the scene title (name only, no detail).
        # Winner has performer name + scene title in detail.
        # They should match because the nominee name appears in winner detail.
        w = Nominee(name='Chanel Camryn & Milan Ponjevic', detail='"Midnight Movie"')
        n = Nominee(name='"Midnight Movie"', detail="")
        assert _nominee_matches_winner(n, w) is True

    def test_substring_match(self):
        w = Nominee(name="Deadly Vows")
        n = Nominee(name="Deadly Vows")
        assert _nominee_matches_winner(n, w) is True

    def test_no_match(self):
        w = Nominee(name="Tommy Pistol", detail="Strip")
        n = Nominee(name="Chad White", detail="Another Film")
        assert _nominee_matches_winner(n, w) is False


class TestMergeWinners:
    def test_exact_match(self):
        cats = [Category(name="Best Actor", nominees=[Nominee("Alice"), Nominee("Bob")])]
        winners = [Category(name="Best Actor", winner=Nominee("Alice"))]
        merge_winners(cats, winners)
        assert cats[0].winner.name == "Alice"

    def test_no_match_leaves_winner_none(self):
        cats = [Category(name="Best Actor", nominees=[Nominee("Alice")])]
        winners = [Category(name="Best Director", winner=Nominee("Bob"))]
        merge_winners(cats, winners)
        assert cats[0].winner is None

    def test_substring_fallback(self):
        cats = [Category(name="Best Anal Sex Scene")]
        winners = [Category(name="Best Anal Sex Scene", winner=Nominee("Jane Doe"))]
        merge_winners(cats, winners)
        assert cats[0].winner.name == "Jane Doe"

    def test_multiple_categories(self):
        cats = [
            Category(name="Best Actor"),
            Category(name="Best Actress"),
        ]
        winners = [
            Category(name="Best Actor", winner=Nominee("Tommy")),
            Category(name="Best Actress", winner=Nominee("Jane")),
        ]
        merge_winners(cats, winners)
        assert cats[0].winner.name == "Tommy"
        assert cats[1].winner.name == "Jane"
