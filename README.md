# awardsparser

A command-line tool that generates Wikipedia-style award tables for the AVN Awards (and similar shows). It parses nominees and winners from the official AVN website and produces wikitext ready to paste into Wikipedia.

## Requirements

- Python 3.11+
- A virtual environment with the required packages

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install playwright beautifulsoup4
playwright install chromium
```

## Usage

### Nominees only

Generates a table with all nominees. Winners are marked *TBA*.

```bash
python awardsparser.py --nominees https://avn.com/awards/2026_nominees --output output.wiki
```

### Nominees + winners

Fetches both pages and marks the winner in bold at the top of each category.

```bash
python awardsparser.py \
  --nominees https://avn.com/awards/2026_nominees \
  --winners  https://avn.com/news/video/2026-avn-award-winners-announced-180971 \
  --output   output.wiki
```

### Winners only

If the nominees page is not yet available, you can run with just the winners URL.

```bash
python awardsparser.py --winners https://avn.com/news/video/2026-avn-award-winners-announced-180971 --output output.wiki
```

### Update mode — preserve existing Wikipedia links (`--update YEAR`)

Wikipedia editors often add `[[hyperlinks]]` to an existing (incomplete) article before all results are published. Use `--update` to pull those links from the existing Wikipedia page and weave them into the generated output, so no previously added links are lost.

```bash
python awardsparser.py \
  --nominees https://avn.com/awards/2026_nominees \
  --winners  https://avn.com/news/video/2026-avn-award-winners-announced-180971 \
  --update   2026 \
  --output   output.wiki
```

The year is automatically mapped to the correct Wikipedia article title:

| Year | Article |
|------|---------|
| 2025 | 42nd AVN Awards |
| 2026 | 43rd AVN Awards |
| 2027 | 44th AVN Awards |

The formula is `ceremony number = year − 1983`.

#### Validation

After fetching the article, the tool checks that it actually covers the expected year. If the formula is wrong (e.g. because a ceremony was skipped or renumbered), you will see an error like:

```
[!] Error: The Wikipedia article '44th AVN Awards' does not appear to cover 2027.
    This can happen when ceremonies were skipped or renumbered.
    Please find the correct article URL and re-run with:
      --update 2027 --update-url <wikipedia-url>
```

Pass `--update-url` with the correct Wikipedia page URL to override the auto-computed title:

```bash
python awardsparser.py \
  --nominees https://avn.com/awards/2027_nominees \
  --update   2027 \
  --update-url https://en.wikipedia.org/wiki/44th_AVN_Awards \
  --output   output.wiki
```

#### How wikilinks are applied

Links are read **verbatim from the existing Wikipedia article** — the tool never guesses or invents link targets. If an editor wrote `[[Tommy Pistol]]`, that exact markup is used. If they wrote `[[Tommy Pistol (actor)|Tommy Pistol]]`, that is used instead. Matching is strict: `"Digital Playground/Pulse"` will **not** pick up a `[[Digital Playground]]` link.

## Output format

The tool produces a Wikipedia wikitable with two award categories per row. Each cell contains the `{{Award category}}` template header followed by a bullet list — winner in bold, nominees indented below.

```wikitext
{| class="wikitable"
|-
| style="width:50%; vertical-align:top;" | {{Award category|#89cff0|Grand Reel}}
* '''[[Strip (film)|Strip]]''' – ''Dorcel/Pulse''
** [[The Blueprint]] – ''Blacked/Pulse''
** Deadly Vows – ''Digital Playground''
| style="width:50%; vertical-align:top;" | {{Award category|#89cff0|Best All-Girl Movie or Series}}
* '''Escape From Camp Conversion''' – ''Girlcore/Adult Time/Pulse''
** Cravings 4 – ''Slayed/Pulse''
|}
```

## Options

| Flag | Description |
|------|-------------|
| `--nominees URL` | URL of the AVN nominees page |
| `--winners URL` | URL of the AVN winners announcement page |
| `--update YEAR` | Fetch the existing Wikipedia article for this year and preserve its `[[wikilinks]]` |
| `--update-url URL` | Override the auto-computed Wikipedia URL for `--update` (use when the ceremony was skipped or renumbered) |
| `--output FILE` / `-o FILE` | Write output to a file instead of stdout |
| `--show NAME` | Award show name (default: `AVN Awards`) |
