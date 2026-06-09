#!/usr/bin/env python3
"""
Awards show Wikipedia table generator.

Usage:
    python awardsparser.py --nominees <url> [--winners <url>] [--output <file>]
    python awardsparser.py --winners <url> [--output <file>]
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from itertools import groupby
from typing import Optional

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Nominee:
    name: str
    detail: str = ""  # film/scene/studio


@dataclass
class Category:
    name: str
    section: str = ""
    nominees: list[Nominee] = field(default_factory=list)
    winner: Optional[Nominee] = None


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60_000)
        html = page.content()
        browser.close()
    return html


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return re.sub(r"[\s\xa0]+", " ", text).strip()


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _is_all_caps(text: str) -> bool:
    """True for ALL-CAPS section headings like 'PLEASURE PRODUCTS'."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _parse_performer_and_title(text: str) -> Nominee:
    """
    Split 'Performer(s), "Scene Title" | Studio' into Nominee(name, detail).
    The title, if present, becomes the detail field.
    """
    text = text.strip().lstrip(",").strip()
    # Quoted title pattern: everything before the opening quote → performers
    m = re.search(r'^(.*?),?\s*"(.+?)"(.*)$', text)
    if m:
        name_part = m.group(1).strip().strip(",").strip()
        title_part = ('"' + m.group(2) + '"' + m.group(3)).strip()
        if name_part:
            return Nominee(name=name_part, detail=title_part)
        return Nominee(name=title_part)
    # No quoted title — split on separator (last resort: comma)
    for sep in (" | ", " – ", " - ", ", "):
        if sep in text:
            parts = text.split(sep, 1)
            return Nominee(name=parts[0].strip(), detail=parts[1].strip())
    return Nominee(name=text)


# ---------------------------------------------------------------------------
# Parsing – winners page
#
# Structure (confirmed from live page):
#   <p><strong>Category Name</strong></p>   ← category label (strong text == full p text)
#   <p>Winner Name, "Title" | Studio</p>    ← winner line (may or may not have <strong>)
#   … repeated …
#   <p><strong>ALL CAPS HEADING</strong></p> ← section header
# ---------------------------------------------------------------------------

def _is_category_label(p: Tag) -> bool:
    """True if <p> consists entirely of a single <strong> (= category name)."""
    text = _clean(p.get_text())
    strongs = p.find_all("strong")
    if not strongs or not text:
        return False
    strong_text = _clean(strongs[0].get_text())
    # The strong must cover essentially all of the paragraph text
    return _normalize(strong_text) == _normalize(text)


def parse_winners_page(html: str) -> list[Category]:
    soup = BeautifulSoup(html, "html.parser")
    categories: list[Category] = []
    current_section = ""

    paras = [p for p in soup.find_all("p") if _clean(p.get_text())]

    i = 0
    while i < len(paras):
        p = paras[i]
        text = _clean(p.get_text())

        # Section header: ALL CAPS paragraph
        if _is_all_caps(text) and _is_category_label(p):
            current_section = text.title()  # convert to Title Case for Wikipedia
            i += 1
            continue

        # Category label
        if _is_category_label(p):
            category_name = text
            # Look ahead for the winner line (next non-label paragraph)
            j = i + 1
            winner: Optional[Nominee] = None
            if j < len(paras):
                next_text = _clean(paras[j].get_text())
                if next_text and not _is_category_label(paras[j]) and not _is_all_caps(next_text):
                    winner = _parse_performer_and_title(next_text)
                    i = j + 1
                else:
                    i += 1
            else:
                i += 1

            categories.append(Category(
                name=category_name,
                section=current_section,
                winner=winner,
                nominees=[winner] if winner else [],
            ))
            continue

        i += 1

    return categories


# ---------------------------------------------------------------------------
# Parsing – nominees page
#
# AVN nominees page structure (confirmed from live page):
#   <p><strong>Category Name</strong></p>   ← category label (same as winners page)
#   <p>                                     ← nominees paragraph
#     [text node: performer names]
#     <strong>scene/film title</strong>     ← each nominee's key identifier is bold
#     [text node: studio info]
#     ... repeated per nominee ...
#   </p>
#   <p>&nbsp;</p>                           ← spacer
#
# Nominees are concatenated in one paragraph; splitting at each <strong>
# boundary recovers individual nominee entries.
#
# Fallbacks for other page layouts:
#   A) <h4>Category</h4> followed by <ul><li>Nominee</li>…</ul>
#   B) Generic: any <ul> preceded by a heading-like element
# ---------------------------------------------------------------------------

def parse_nominees_page(html: str) -> list[Category]:
    soup = BeautifulSoup(html, "html.parser")

    # Primary: AVN-style category-label + concatenated-nominees paragraphs
    categories = _parse_avn_nominees(soup)
    if categories:
        return categories

    # Fallback A: h4 + ul
    categories = _parse_h4_ul(soup)
    if categories:
        return categories

    # Fallback B: generic ul
    return _parse_generic_ul(soup)


def _parse_avn_nominees(soup: BeautifulSoup) -> list[Category]:
    """
    Handle the AVN nominees page pattern: category label <p> followed by a
    nominees <p> whose content is a run of [text][<strong>title</strong>][text]...
    """
    categories: list[Category] = []
    current_section = ""
    paras = [p for p in soup.find_all("p") if _clean(p.get_text())]

    i = 0
    while i < len(paras):
        p = paras[i]
        text = _clean(p.get_text())

        # Section header (ALL CAPS)
        if _is_all_caps(text) and _is_category_label(p):
            current_section = text.title()
            i += 1
            continue

        # Category label
        if _is_category_label(p):
            category_name = text
            j = i + 1
            nominees: list[Nominee] = []

            # The nominees paragraph is the next non-empty, non-label para
            if j < len(paras):
                np = paras[j]
                np_text = _clean(np.get_text())
                if np_text and not _is_category_label(np) and not _is_all_caps(np_text):
                    nominees = _split_nominees_paragraph(np)
                    i = j + 1
                else:
                    i += 1
            else:
                i += 1

            if nominees:
                categories.append(Category(
                    name=category_name,
                    section=current_section,
                    nominees=nominees,
                ))
            continue

        i += 1

    return categories


def _split_nominees_paragraph(p: Tag) -> list[Nominee]:
    """
    Split a nominees paragraph into individual Nominee objects.

    The paragraph interleaves plain text (performer names / leading text) and
    <strong> elements (scene/film titles).  Each nominee entry is either:
      - A standalone <strong> (film title with no preceding performer text), or
      - Plain text (performer names) + following <strong> (scene title) + trailing plain text (studio)

    Strategy: collect (pre_text, strong_text, post_text) triples.
    """
    nominees: list[Nominee] = []
    children = list(p.children)

    # If the paragraph uses <br/> as separators (e.g. performer-only categories),
    # split on those directly.
    if any(getattr(child, 'name', None) == 'br' for child in children):
        parts = p.decode_contents().split('<br/>')
        for part in parts:
            text = _clean(BeautifulSoup(part, "html.parser").get_text())
            if text and text != '\xa0':
                nominees.append(_parse_performer_and_title(text))
        return nominees

    # Build a flat list of tokens: ('text', value) or ('strong', value)
    tokens: list[tuple[str, str]] = []
    for child in children:
        if hasattr(child, 'get_text'):
            t = _clean(child.get_text())
            if t and t != '\xa0':
                tokens.append(('strong' if child.name in ('strong', 'b') else 'text', t))
        else:
            t = _clean(str(child))
            if t and t != '\xa0':
                tokens.append(('text', t))

    if not tokens:
        return []

    # If no strongs at all, treat the whole paragraph as one nominee
    if all(kind == 'text' for kind, _ in tokens):
        full = " ".join(v for _, v in tokens)
        return [_parse_performer_and_title(full)]

    # Group into nominee chunks: each chunk starts at a 'strong' token.
    # Text tokens before the first strong are a prefix (performer name).
    chunks: list[str] = []
    current: list[str] = []

    # Pre-strong text
    idx = 0
    pre_strong: list[str] = []
    while idx < len(tokens) and tokens[idx][0] == 'text':
        pre_strong.append(tokens[idx][1])
        idx += 1

    while idx < len(tokens):
        kind, val = tokens[idx]
        if kind == 'strong':
            if current:
                chunks.append(" ".join(current))
            pre = " ".join(pre_strong).strip(", ").strip()
            current = [pre + ", " + val if pre else val]
            pre_strong = []
        else:
            current.append(val)
        idx += 1

    if current:
        chunks.append(" ".join(current))

    for chunk in chunks:
        chunk = chunk.strip().strip(",").strip()
        if chunk:
            nominees.append(_parse_performer_and_title(chunk))

    return nominees


def _nearest_section(tag: Tag) -> str:
    for prev in tag.find_all_previous(["h2", "h3"]):
        return _clean(prev.get_text())
    return ""


def _nominees_from_ul(ul: Tag) -> list[Nominee]:
    nominees = []
    for li in ul.find_all("li", recursive=False):
        text = _clean(li.get_text())
        if text:
            nominees.append(_parse_performer_and_title(text))
    return nominees


def _parse_h4_ul(soup: BeautifulSoup) -> list[Category]:
    categories = []
    for h4 in soup.find_all("h4"):
        name = _clean(h4.get_text())
        if not name or len(name) > 150:
            continue
        ul = h4.find_next_sibling(["ul", "ol"])
        if ul:
            nominees = _nominees_from_ul(ul)
            if nominees:
                categories.append(Category(name=name, section=_nearest_section(h4),
                                           nominees=nominees))
    return categories


def _parse_generic_ul(soup: BeautifulSoup) -> list[Category]:
    categories = []
    for ul in soup.find_all("ul"):
        items = ul.find_all("li", recursive=False)
        if len(items) < 2:
            continue
        prev = ul.find_previous_sibling()
        label = _clean(prev.get_text()) if prev else ""
        if not label:
            continue
        nominees = _nominees_from_ul(ul)
        if nominees:
            categories.append(Category(name=label, nominees=nominees))
    return categories


# ---------------------------------------------------------------------------
# Merge winners into nominee categories
# ---------------------------------------------------------------------------

def merge_winners(categories: list[Category], winner_cats: list[Category]) -> None:
    winner_map = {_normalize(c.name): c.winner for c in winner_cats if c.winner}

    for cat in categories:
        key = _normalize(cat.name)
        if key in winner_map:
            cat.winner = winner_map[key]
        else:
            # Substring fallback
            for wk, wv in winner_map.items():
                if key and wk and (key in wk or wk in key):
                    cat.winner = wv
                    break


# ---------------------------------------------------------------------------
# Wikipedia wikitext output
# ---------------------------------------------------------------------------

def _nominee_matches_winner(nominee: Nominee, winner: Nominee) -> bool:
    """
    True if `nominee` represents the same entry as `winner`.
    Handles cases where winner name = 'Performers, "Title"' and nominee
    name = '"Title"' (the scene title is the key identifier).
    """
    wn = _normalize(winner.name)
    nn = _normalize(nominee.name)
    wd = _normalize(winner.detail)
    nd = _normalize(nominee.detail)
    # Exact match
    if wn == nn:
        return True
    # Substring: one name contains the other (scene title vs full entry)
    if nn and (nn in wn or wn in nn):
        return True
    # Cross-check: nominee name appears in winner detail (e.g. nominee is just
    # the scene title, winner entry has both performers and scene title)
    if nn and wd and nn in wd:
        return True
    # Or nominee detail appears in winner name
    if nd and wn and nd in wn:
        return True
    return False

def _wiki_escape(text: str) -> str:
    """
    Escape bare pipe characters for use in wikitable cells.

    Pipes that are part of [[Article|Display]] wikilinks are valid wiki syntax
    and must NOT be escaped.  Only bare pipes (which would break table cell
    parsing) need replacing with {{!}}.
    """
    result: list[str] = []
    i = 0
    while i < len(text):
        if text[i:i+2] == '[[':
            end = text.find(']]', i + 2)
            if end != -1:
                result.append(text[i:end + 2])
                i = end + 2
                continue
        if text[i] == '|':
            result.append('{{!}}')
        else:
            result.append(text[i])
        i += 1
    return ''.join(result)


# ---------------------------------------------------------------------------
# Wikipedia wikilink extraction  (for --update)
# ---------------------------------------------------------------------------

def _ordinal(n: int) -> str:
    """Return the ordinal string for n, e.g. 43 → '43rd'."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _avn_wikipedia_title(year: int) -> str:
    """
    Map a ceremony year to its Wikipedia article title.
    2026 → '43rd AVN Awards'  (year - 1983 = ceremony number)
    """
    number = year - 1983
    return f"{_ordinal(number)} AVN Awards"


def fetch_wikipedia_wikitext(title: str) -> str:
    """Fetch the raw wikitext of a Wikipedia article via the MediaWiki API."""
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    url = (
        "https://en.wikipedia.org/w/api.php"
        f"?action=query&titles={encoded}&prop=revisions"
        "&rvprop=content&rvslots=main&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "awardsparser/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    if "missing" in page:
        return ""
    return page["revisions"][0]["slots"]["main"]["*"]


def _title_from_wikipedia_url(url: str) -> str:
    """Extract the article title from a Wikipedia URL."""
    # e.g. https://en.wikipedia.org/wiki/43rd_AVN_Awards → '43rd AVN Awards'
    match = re.search(r'/wiki/([^#?]+)', url)
    if not match:
        raise ValueError(f"Could not parse Wikipedia article title from URL: {url}")
    return urllib.parse.unquote(match.group(1)).replace("_", " ")


def validate_wikipedia_article(wikitext: str, year: int, title: str) -> None:
    """
    Verify that the fetched article actually covers the expected ceremony year.
    Raises SystemExit with a helpful message if the year is not found.
    """
    if str(year) not in wikitext:
        print(
            f"\n[!] Error: The Wikipedia article '{title}' does not appear to cover {year}.\n"
            f"    This can happen when ceremonies were skipped or renumbered.\n"
            f"    Please find the correct article URL and re-run with:\n"
            f"      --update {year} --update-url <wikipedia-url>\n",
            file=sys.stderr,
        )
        sys.exit(1)


def extract_wikilinks(wikitext: str) -> dict[str, str]:
    """
    Return a dict mapping normalised display text → full wikilink markup,
    reading the *actual link target* from each [[…]] in the existing article.

    [[Article]]           → key=normalise("Article"),  value="[[Article]]"
    [[Article|Display]]   → key=normalise("Display"),  value="[[Article|Display]]"

    We never guess or invent link targets — every entry here came verbatim
    from the existing Wikipedia page, so if an editor wrote [[Tommy Pistol]]
    we use exactly that; if they wrote [[Tommy Pistol (actor)|Tommy Pistol]]
    we use that instead.  Matching is strict exact-normalised-key only
    (no substring), so "Digital Playground/Pulse" will NOT pick up a link
    for "Digital Playground".

    Skips namespace links (File:, Category:, Template:, etc.).
    """
    links: dict[str, str] = {}
    for m in re.finditer(r'\[\[([^\[\]]+)\]\]', wikitext):
        inner = m.group(1)
        article_part = inner.split("|")[0].strip()
        if ":" in article_part:          # skip File:, Category:, Template:, …
            continue
        parts = inner.split("|", 1)
        display = parts[1].strip() if len(parts) == 2 else parts[0].strip()
        key = _normalize(display)
        if key:
            # If the same display text appears with different link targets,
            # keep the first occurrence (mirrors what readers see).
            links.setdefault(key, f"[[{inner}]]")
    return links


# ---------------------------------------------------------------------------
# Header color matching the AVN Awards Wikipedia page
AVN_HEADER_COLOR = "#89cff0"


def _apply_wikilink(text: str, wikilinks: dict[str, str]) -> str:
    """Replace `text` with its wikilink markup if one exists in the lookup."""
    key = _normalize(text)
    return wikilinks[key] if key in wikilinks else text


def _format_entry(n: Nominee, bold: bool = False,
                  wikilinks: Optional[dict[str, str]] = None) -> str:
    """
    Format a nominee entry as wikitext inline text.
    e.g. '''Tommy Pistol''' – ''Strip'', Dorcel/Pulse

    If `wikilinks` is provided, any name/title that matches an existing
    Wikipedia link from the --update page is wrapped in [[…]] markup.
    """
    wl = wikilinks or {}

    # Work on raw (unescaped) strings so separator-stripping logic sees the
    # original characters; wiki-escape only at the very end.
    raw_name = _apply_wikilink(n.name, wl)
    raw_detail = n.detail or ""

    if bold:
        display_name = f"'''{_wiki_escape(raw_name)}'''"
    else:
        display_name = _wiki_escape(raw_name)

    if raw_detail:
        # Scene/film title in italics, rest plain.
        # Try to split a quoted title from trailing studio info.
        m = re.match(r'^(".*?")(.*)', raw_detail)
        if m:
            quoted_title = m.group(1)
            inner = quoted_title.strip('"')
            linked_title = _apply_wikilink(inner, wl)
            title_part = f"''{_wiki_escape(linked_title if linked_title != inner else quoted_title)}''"
            # Strip any leading separator (| – - ,) left over from the source
            rest = re.sub(r'^[\s|,–\-]+', '', m.group(2)).strip()
            detail_fmt = title_part + (f", {_wiki_escape(rest)}" if rest else "")
        else:
            detail_fmt = f"''{_wiki_escape(_apply_wikilink(raw_detail, wl))}''"
        line = f"{display_name} – {detail_fmt}"
    else:
        line = display_name

    return line


def generate_wikitext(categories: list[Category], show_name: str = "AVN Awards",
                      header_color: str = AVN_HEADER_COLOR,
                      wikilinks: Optional[dict[str, str]] = None) -> str:
    """
    Produces Wikipedia-style two-column wikitable output.

    If `wikilinks` is provided (populated via --update), any name or title
    that matches an existing [[wikilink]] on the Wikipedia page is
    preserved/inserted into the output automatically.
    """
    if not categories:
        return "<!-- No categories found -->"

    wl = wikilinks or {}
    has_winners = any(c.winner for c in categories)
    has_nominees = any(len(c.nominees) > 1 for c in categories)

    lines = []
    for section, cats in groupby(categories, key=lambda c: c.section):
        cat_list = list(cats)
        if section:
            lines.append(f"\n=== {section} ===\n")

        lines.append('{| class="wikitable"')

        # Pair categories two per row (matching the AVN/Oscars Wikipedia layout)
        for i in range(0, len(cat_list), 2):
            lines.append("|-")
            for cat in cat_list[i:i + 2]:
                cat_name = _wiki_escape(cat.name)
                # Category header and nominees list in the SAME cell
                cell = f'| style="width:50%; vertical-align:top;" | {{{{Award category|{header_color}|{cat_name}}}}}\n'
                if has_winners and cat.winner:
                    winner_line = _format_entry(cat.winner, bold=True, wikilinks=wl)
                    cell += f"* {winner_line}\n"
                    if has_nominees:
                        others = [n for n in cat.nominees
                                  if not _nominee_matches_winner(n, cat.winner)]
                        for n in others:
                            cell += f"** {_format_entry(n, wikilinks=wl)}\n"
                elif has_nominees:
                    for n in cat.nominees:
                        cell += f"* {_format_entry(n, wikilinks=wl)}\n"
                else:
                    cell += "''TBA''\n"
                lines.append(cell.rstrip())

        lines.append("|}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 1 — "Films with multiple nominations and awards" section
#
# Mirrors the format on https://en.wikipedia.org/wiki/98th_Academy_Awards
# Two side-by-side {{col-begin}} wikitables: nominations count and wins count.
# ---------------------------------------------------------------------------

def _extract_film_key(n: Nominee) -> Optional[str]:
    """
    Extract the film/title identifier from a nominee entry for counting.

    Priority:
    1. Quoted title in detail field → that is the scene/film title.
    2. Name that looks like a film title (no comma, no ' and ') → use name.
    Otherwise return None (can't confidently identify a film).
    """
    if n.detail:
        m = re.match(r'^"(.+?)"', n.detail)
        if m:
            return m.group(1)
    if n.name and ',' not in n.name and ' and ' not in n.name.lower():
        return n.name
    return None


def _make_count_table(caption: str, col_header: str,
                       entries: list[tuple[str, int]],
                       wl: dict[str, str]) -> list[str]:
    """Build a wikitable mapping count → film title (with rowspan for ties)."""
    lines = [
        '{| class="wikitable plainrowheaders" style="text-align: center; margin-right:1em;"',
        f'|+ {caption}',
        '|-',
        f'! scope="col" style="width:55px;"| {col_header}',
        '! scope="col" style="text-align:center;"| Film',
    ]
    i = 0
    while i < len(entries):
        count = entries[i][1]
        group: list[str] = []
        while i < len(entries) and entries[i][1] == count:
            group.append(entries[i][0])
            i += 1
        for k, title in enumerate(group):
            lines.append('|-')
            if k == 0:
                span = f' rowspan="{len(group)}"' if len(group) > 1 else ''
                lines.append(f'| scope="row"{span}| {count}')
            linked = _apply_wikilink(title, wl)
            lines.append(f"| ''{_wiki_escape(linked)}''")
    lines.append('|}')
    return lines


def generate_multi_nominations_table(
        categories: list[Category],
        wikilinks: Optional[dict[str, str]] = None) -> str:
    """
    Generate a "Films with multiple nominations and awards" section.

    Each film/title is counted once per category even if it appears multiple
    times in the same category's nominee list.
    """
    wl = wikilinks or {}
    nom_counts: dict[str, int] = {}
    win_counts: dict[str, int] = {}

    for cat in categories:
        seen: set[str] = set()
        for n in cat.nominees:
            film = _extract_film_key(n)
            if film and film not in seen:
                nom_counts[film] = nom_counts.get(film, 0) + 1
                seen.add(film)
        if cat.winner:
            film = _extract_film_key(cat.winner)
            if film:
                win_counts[film] = win_counts.get(film, 0) + 1

    multi_noms = sorted(
        ((k, v) for k, v in nom_counts.items() if v >= 2),
        key=lambda x: (-x[1], x[0]),
    )
    multi_wins = sorted(
        ((k, v) for k, v in win_counts.items() if v >= 2),
        key=lambda x: (-x[1], x[0]),
    )

    lines: list[str] = [
        "== Films with multiple nominations and awards ==",
        "{{col-begin|width=70%}}",
        "{{col-1-of-2}}",
        "",
    ]
    lines += _make_count_table(
        "Films with multiple nominations", "Nominations", multi_noms, wl)
    lines += ["", "{{col-2-of-2}}", ""]
    lines += _make_count_table(
        "Films with multiple wins", "Awards", multi_wins, wl)
    lines += ["", "{{col-end}}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 2 — Main AVN Awards page: new year column
#
# The AVN Awards article has a horizontal wikitable with years as columns and
# award categories as rows.  This generates the cell values for a new year so
# they can be pasted into the Wikipedia table editor.
# ---------------------------------------------------------------------------

# Category order as it appears in the current (2025–) table on the main page.
# Display names must match the row-header text on Wikipedia exactly.
MAIN_PAGE_CATEGORIES: list[str] = [
    "Best New Starlet",
    "Female Performer of the Year",
    "Male Performer of the Year",
    "Trans Performer of the Year",
    "Best Male Newcomer",
    "Best Actress – Featurette",
    "Best Actor – Featurette",
    "Best Leading Actress",
    "Best Leading Actor",
    "Best Supporting Actress",
    "Best Supporting Actor",
    "International Female Performer of the Year",
    "International Male Performer of the Year",
    "Outstanding Directing - Individual Work",
    "Best Directing Portfolio – Narrative",
    "Best Directing Portfolio – Non-Narrative",
    "Best Directing Portfolio – International",
    "Best Boy/Girl Sex Scene",
    "Best Girl/Girl Sex Scene",
    "Best All-Girl Group Sex Scene",
    "Most Outrageous Sex Scene",
    "MILF Performer of the Year",
    "Best All-Girl Series or Free-Form Line",
    "Best MILF/Female Mixed-Age Series or Free-Form Line",
    "Best International Production",
    "Mark Stone Award for Outstanding Comedy",
    "Best Web Retail Store",
]


def _format_main_page_cell(winner: Optional[Nominee],
                            wl: dict[str, str]) -> str:
    """
    Format a winner as a cell for the AVN Awards main-page horizontal table.

    Uses {{spaced ndash}} (Wikipedia's convention for that table) rather than
    the literal em-dash used in ceremony tables.

    e.g. [[Kira Noir]]{{spaced ndash}} ''Machine Gunner''
    """
    if not winner:
        return "''TBA''"
    raw_name = _apply_wikilink(winner.name, wl)
    name_part = _wiki_escape(raw_name)
    if winner.detail:
        m = re.match(r'^"(.+?)"(.*)', winner.detail)
        if m:
            inner = m.group(1)
            linked = _apply_wikilink(inner, wl)
            film_part = f"''{_wiki_escape(linked)}''"
            rest = re.sub(r'^[\s|,–\-]+', '', m.group(2)).strip()
            detail_str = film_part + (f", {_wiki_escape(rest)}" if rest else "")
        else:
            linked_d = _apply_wikilink(winner.detail, wl)
            detail_str = f"''{_wiki_escape(linked_d)}''"
        return f"{name_part}{{{{spaced ndash}}}} {detail_str}"
    return name_part


def generate_main_page_column(
        categories: list[Category],
        year: int,
        wikilinks: Optional[dict[str, str]] = None) -> str:
    """
    Generate the cell content for the new year's column on the AVN Awards
    main Wikipedia page.

    Output is an annotated wikitext block: one cell per table row, in the
    same order as MAIN_PAGE_CATEGORIES, ready to paste into the editor.
    """
    wl = wikilinks or {}
    ceremony_title = _avn_wikipedia_title(year)

    # Build lookup: normalized name → Category
    cat_map: dict[str, Category] = {_normalize(c.name): c for c in categories}

    def _find_cat(display: str) -> Optional[Category]:
        key = _normalize(display)
        if key in cat_map:
            return cat_map[key]
        return next(
            (c for nk, c in cat_map.items() if key in nk or nk in key),
            None,
        )

    lines: list[str] = [
        f"<!-- ================================================================",
        f"     New column for [[AVN Awards]] table — {year} ({ceremony_title})",
        f"     Add the following header to the year row:",
        f"     ![[{ceremony_title}|{year}]]",
        f"     Then add these cells in order (one per category row):",
        f"     ================================================================ -->",
    ]
    for display_name in MAIN_PAGE_CATEGORIES:
        cat = _find_cat(display_name)
        winner = cat.winner if cat else None
        cell = _format_main_page_cell(winner, wl)
        lines += [
            f"<!-- {display_name} -->",
            f"|{cell}",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 3 — Per-category Wikipedia pages
#
# Nine AVN award categories have their own Wikipedia articles.  This feature
# fetches each article, appends a new row for the current year, and writes
# the full updated wikitext so it can be pasted into the Wikipedia editor.
#
# Row format (matching AVN Award for Best Actress etc.):
#   |-
#   |rowspan=N|YEAR<ref>…</ref>
#   |rowspan=N align=center|                  ← photo (left blank)
#   |rowspan=N align=center|'''[[Winner]]'''<br>{{small|'''''Film'''''}}
#   |align=center|Nominee<br>{{small|''Film''}}
#   |-
#   |align=center|Nominee 2<br>{{small|''Film''}}
#   …
# ---------------------------------------------------------------------------

# Normalized category name → Wikipedia article title.
# Keys are produced by _normalize() applied to the display name.
CATEGORY_ARTICLE_MAP: dict[str, str] = {
    "bestactor":                        "AVN Award for Best Actor",
    "bestactress":                      "AVN Award for Best Actress",
    "bestsupportingactor":              "AVN Award for Best Supporting Actor",
    "bestsupportingactress":            "AVN Award for Best Supporting Actress",
    "maleperformeroftheyear":           "AVN Award for Male Performer of the Year",
    "femaleperformeroftheyear":         "AVN Award for Female Performer of the Year",
    "maleforeignperformeroftheyear":    "AVN Award for Male Foreign Performer of the Year",
    "femaleforeignperformeroftheyear":  "AVN Award for Female Foreign Performer of the Year",
    "transgenderperformeroftheyear":    "AVN Award for Transgender Performer of the Year",
}

# Aliases for names the AVN nominees page uses that differ from Wikipedia row headers.
CATEGORY_ARTICLE_ALIASES: dict[str, str] = {
    "internationalmaleperformeroftheyear":      "AVN Award for Male Foreign Performer of the Year",
    "internationalfemaleperformeroftheyear":    "AVN Award for Female Foreign Performer of the Year",
    "transperformeroftheyear":                  "AVN Award for Transgender Performer of the Year",
    "femaleperformeroftheyearaward":            "AVN Award for Female Performer of the Year",
}

# Combined lookup used by the CLI
_ALL_CATEGORY_MAPS: dict[str, str] = {**CATEGORY_ARTICLE_MAP, **CATEGORY_ARTICLE_ALIASES}


def _format_category_page_row(
        year: int,
        winner: Optional[Nominee],
        other_nominees: list[Nominee],
        wikilinks: Optional[dict[str, str]] = None,
        nominees_url: str = "",
        winners_url: str = "") -> str:
    """
    Format a new row block for a per-category Wikipedia article.
    The rowspan equals the number of other nominees (≥1).
    """
    wl = wikilinks or {}
    n_rows = max(len(other_nominees), 1)

    # Build <ref> block
    refs_parts: list[str] = []
    if nominees_url:
        refs_parts.append(
            f'{{{{Cite web|title={year} AVN Award Nominees Announced'
            f'|url={nominees_url}|website=[[AVN (magazine)|AVN]]}}}}'
        )
    if winners_url:
        refs_parts.append(
            f'{{{{Cite web|title={year} AVN Award Winners Announced'
            f'|url={winners_url}|website=[[AVN (magazine)|AVN]]}}}}'
        )
    refs = "".join(f"<ref>{r}</ref>" for r in refs_parts)

    def _winner_fmt(w: Nominee) -> str:
        raw_name = _apply_wikilink(w.name, wl)
        name = f"'''{ _wiki_escape(raw_name) }'''"
        if w.detail:
            m = re.match(r'^"(.+?)"', w.detail)
            film_raw = m.group(1) if m else w.detail
            linked = _apply_wikilink(film_raw, wl)
            film_cell = "{{small|" + "'''''" + _wiki_escape(linked) + "'''''" + "}}"
            return name + "<br>" + film_cell
        return name

    def _nom_fmt(n: Nominee) -> str:
        raw_name = _apply_wikilink(n.name, wl)
        name = _wiki_escape(raw_name)
        if n.detail:
            m = re.match(r'^"(.+?)"', n.detail)
            film_raw = m.group(1) if m else n.detail
            linked = _apply_wikilink(film_raw, wl)
            film_cell = "{{small|" + "''" + _wiki_escape(linked) + "''" + "}}"
            return name + "<br>" + film_cell
        return name

    rs = f"rowspan={n_rows} " if n_rows > 1 else ""
    winner_content = _winner_fmt(winner) if winner else "''TBA''"

    rows: list[str] = ['|-']
    rows.append(f"|{rs}|{year}{refs}")
    rows.append(f"|{rs}align=center|")
    rows.append(f"|{rs}align=center|{winner_content}")

    first_nom = other_nominees[0] if other_nominees else None
    rows.append(f"|align=center|{_nom_fmt(first_nom)}" if first_nom else "|align=center|")

    for nom in other_nominees[1:]:
        rows.append('|-')
        rows.append(f"|align=center|{_nom_fmt(nom)}")

    return "\n".join(rows)


def _insert_row_before_table_end(wikitext: str, new_row: str) -> str:
    """Insert new_row wikitext before the last |} line in the article."""
    lines = wikitext.split('\n')
    for i in range(len(lines) - 1, -1, -1):
        if re.match(r'^\s*\|}\s*$', lines[i]):
            lines.insert(i, new_row)
            return '\n'.join(lines)
    return wikitext + '\n' + new_row


def generate_category_page_update(
        article_title: str,
        cat: Category,
        year: int,
        wikilinks: Optional[dict[str, str]] = None,
        nominees_url: str = "",
        winners_url: str = "") -> str:
    """
    Fetch the existing Wikipedia article for a per-category page, append the
    new year's row, and return the complete updated wikitext.
    """
    print(f"[*]   Fetching '{article_title}' …", file=sys.stderr)
    existing = fetch_wikipedia_wikitext(article_title)
    if not existing:
        print(f"[!]   Could not fetch '{article_title}' — skipping.", file=sys.stderr)
        return ""

    wl = wikilinks or {}
    winner = cat.winner
    others = [n for n in cat.nominees
              if winner is None or not _nominee_matches_winner(n, winner)]

    new_row = _format_category_page_row(
        year=year,
        winner=winner,
        other_nominees=others,
        wikilinks=wl,
        nominees_url=nominees_url,
        winners_url=winners_url,
    )
    return _insert_row_before_table_end(existing, new_row)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_all_outputs(
        output_dir: str,
        ceremony_wikitext: str,
        categories: list[Category],
        year: int,
        wikilinks: dict[str, str],
        nominees_url: str,
        winners_url: str) -> None:
    """Write all Wikipedia page outputs to output_dir."""
    os.makedirs(output_dir, exist_ok=True)

    def _write(filename: str, text: str) -> None:
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[*]   {filename}", file=sys.stderr)

    print(f"[*] Writing outputs to {output_dir}/", file=sys.stderr)

    # 1. Main ceremony table (same as --output mode)
    _write("ceremony.wiki", ceremony_wikitext)

    # 2. Films with multiple nominations and awards
    _write("multi_noms_and_wins.wiki",
           generate_multi_nominations_table(categories, wikilinks=wikilinks))

    # 3. New year column for the AVN Awards main page
    _write("main_page_column.wiki",
           generate_main_page_column(categories, year, wikilinks=wikilinks))

    # 4. Per-category Wikipedia page updates
    written = 0
    for cat in categories:
        article_title = _ALL_CATEGORY_MAPS.get(_normalize(cat.name))
        if not article_title:
            continue
        slug = re.sub(r'[^a-z0-9]+', '_', article_title.lower()).strip('_')
        updated = generate_category_page_update(
            article_title=article_title,
            cat=cat,
            year=year,
            wikilinks=wikilinks,
            nominees_url=nominees_url,
            winners_url=winners_url,
        )
        if updated:
            _write(f"{slug}.wiki", updated)
            written += 1

    print(f"[*] Done — {written} category page(s) updated.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Generate Wikipedia award tables from nominees/winners pages."
    )
    parser.add_argument("--nominees", help="URL of the nominees page")
    parser.add_argument("--winners", help="URL of the winners announcement page")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument("--show", default="AVN Awards", help="Award show name")
    parser.add_argument(
        "--update", metavar="YEAR", type=int,
        help=(
            "Fetch the existing Wikipedia article for this ceremony year "
            "(e.g. 2026 → '43rd AVN Awards') and preserve any [[wikilinks]] "
            "already present there in the generated output."
        ),
    )
    parser.add_argument(
        "--update-url", metavar="URL",
        help=(
            "Wikipedia URL of the existing article to use with --update, "
            "overriding the auto-computed title. Use this if the ceremony "
            "number formula is wrong (e.g. due to a skipped year)."
        ),
    )
    parser.add_argument(
        "--output-dir", metavar="DIR",
        help=(
            "Write all Wikipedia page outputs to a directory. Generates: "
            "ceremony.wiki, multi_noms.wiki, main_page_column.wiki, and one "
            "<article>.wiki per linked category page. Requires --update YEAR."
        ),
    )
    args = parser.parse_args()

    if not args.nominees and not args.winners:
        parser.error("At least one of --nominees or --winners is required.")

    if args.update_url and not args.update:
        parser.error("--update-url requires --update YEAR.")
    if args.output_dir and not args.update:
        parser.error("--output-dir requires --update YEAR.")

    # ------------------------------------------------------------------
    # Optionally harvest existing wikilinks from the Wikipedia article
    # ------------------------------------------------------------------
    wikilinks: dict[str, str] = {}
    if args.update:
        # Resolve article title: prefer explicit URL, otherwise compute from year
        if args.update_url:
            title = _title_from_wikipedia_url(args.update_url)
        else:
            title = _avn_wikipedia_title(args.update)

        print(f"[*] Fetching existing Wikipedia article: '{title}'", file=sys.stderr)
        wikitext_existing = fetch_wikipedia_wikitext(title)

        if not wikitext_existing:
            if args.update_url:
                print(
                    f"\n[!] Error: The Wikipedia article '{title}' was not found.\n"
                    f"    Please check the URL and try again.\n",
                    file=sys.stderr,
                )
            else:
                print(
                    f"\n[!] Error: Could not find Wikipedia article '{title}'.\n"
                    f"    The ceremony number formula (year − 1983) may be incorrect\n"
                    f"    for {args.update} (e.g. if a ceremony was skipped or renumbered).\n"
                    f"    Find the correct article URL and re-run with:\n"
                    f"      --update {args.update} --update-url <wikipedia-url>\n",
                    file=sys.stderr,
                )
            sys.exit(1)

        # Validate the article actually covers the expected year
        validate_wikipedia_article(wikitext_existing, args.update, title)

        wikilinks = extract_wikilinks(wikitext_existing)
        print(f"[*] Extracted {len(wikilinks)} wikilinks from existing article.", file=sys.stderr)

    categories: list[Category] = []

    if args.nominees:
        print(f"[*] Fetching nominees page: {args.nominees}", file=sys.stderr)
        nominees_html = fetch_html(args.nominees)
        categories = parse_nominees_page(nominees_html)
        print(f"[*] Found {len(categories)} categories from nominees page.", file=sys.stderr)

    if args.winners:
        print(f"[*] Fetching winners page: {args.winners}", file=sys.stderr)
        winners_html = fetch_html(args.winners)
        winner_cats = parse_winners_page(winners_html)
        print(f"[*] Found {len(winner_cats)} winners.", file=sys.stderr)

        if categories:
            merge_winners(categories, winner_cats)
            matched = sum(1 for c in categories if c.winner)
            print(f"[*] Matched {matched}/{len(categories)} categories to winners.", file=sys.stderr)
            # Append winner-only categories that had no nominee counterpart
            nominee_keys = {_normalize(c.name) for c in categories}
            extras = [c for c in winner_cats
                      if not any(_normalize(c.name) in nk or nk in _normalize(c.name)
                                 for nk in nominee_keys)]
            if extras:
                print(f"[*] Appending {len(extras)} winners-only categories.", file=sys.stderr)
                categories.extend(extras)
        else:
            categories = winner_cats

    wikitext = generate_wikitext(categories, show_name=args.show, wikilinks=wikilinks)

    if args.output_dir:
        _write_all_outputs(
            output_dir=args.output_dir,
            ceremony_wikitext=wikitext,
            categories=categories,
            year=args.update,
            wikilinks=wikilinks,
            nominees_url=args.nominees or "",
            winners_url=args.winners or "",
        )
    elif args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(wikitext)
        print(f"[*] Written to {args.output}", file=sys.stderr)
    else:
        print(wikitext)


if __name__ == "__main__":
    main()
