# mORMot2 Daily

Daily digest of [synopse/mORMot2](https://github.com/synopse/mORMot2) commits,
published as a static site on GitHub Pages.

A scheduled workflow pulls new upstream commits with their diffs,
[Jules](https://jules.google) reviews them and writes one JSON file per edition, the
file is validated against a schema, and the site is generated from it.

```
                 fetch_commits.py            Jules REST API            build_site.py
synopse/mORMot2 ─────────────────► data/raw ──────────────► data/analysis ──────────► _site ──► Pages
                  commits+diffs      (JSON)     PR + schema     (JSON)      HTML/RSS/JSON
                                               validation
```

The reviewer never writes HTML — it writes JSON against
`schema/analysis.schema.json`, checked before merge, and the site is generated from
it. A bad review can be wrong; it cannot break the page.

Per edition: headline, intro, TL;DR, risk level, upstream build number, entries
grouped by category (breaking, security, fixes, features, performance, compiler,
under the hood, tests, housekeeping) with *what changed*, *impact*, an action and the
public API moves. Entries carry `interpretation` when a claim is the reviewer's
reading and `auto-classified` when they never got a review pass. Plus unit index,
archive, activity chart, filter and search, RSS and JSON feeds, light and dark themes.

Type is [Lekton](https://fonts.google.com/specimen/Lekton) (ISIA Urbino, OFL),
self-hosted in `site/assets/fonts/` — no external request. Swap `--font-prose` /
`--font-ui` at the top of `site/assets/style.css` to change it; the reading column is
`--column` in the same block.

## Local use

```bash
pip install -r requirements.txt

# fetch (needs GITHUB_TOKEN to avoid the 60 requests/hour anonymous limit)
GITHUB_TOKEN=… python scripts/fetch_commits.py --since-days 2

# or build a payload from a local clone, no API needed
git clone --depth 60 https://github.com/synopse/mORMot2 /tmp/mormot2
python scripts/make_fixture.py --clone /tmp/mormot2 --date 2026-08-28

python scripts/validate_analysis.py --all
python scripts/build_site.py && python -m http.server -d _site 8000
```

Preview the exact prompt Jules will receive, without spending a session:

```bash
python scripts/run_jules_analysis.py start --edition 2026-08-28 --dry-run
```

## How the daily job handles a bad review

1. Jules opens a pull request with `data/analysis/<edition>.json`.
2. The workflow validates that file against the schema **and** against the raw
   payload: every SHA must resolve to a commit of the edition, at least 90 % of the
   non-merge commits must be covered, headlines may not be copies of commit subjects,
   an `action` that demands work must say what work.
3. If it fails, the errors are sent back into the same Jules session
   (`run_jules_analysis.py feedback`) and the file is re-checked once.
4. If it still fails, the pull request is left open for a human and the site is
   published with the edition marked *not reviewed* — the heuristic classification in
   `scripts/heuristics.py` keeps it readable in the meantime.

## Files

| Path | Role |
|------|------|
| `PROMPT.md` | the editorial brief sent to Jules — edit this to change the voice |
| `AGENTS.md` | repository rules any coding agent should follow here |
| `schema/analysis.schema.json` | the contract between the reviewer and the site |
| `scripts/fetch_commits.py` | incremental upstream fetch with diffs |
| `scripts/jules_api.py` | Jules REST client (sources, sessions, activities, polling) |
| `scripts/run_jules_analysis.py` | session orchestration: start, wait, feedback |
| `scripts/validate_analysis.py` | schema + semantic validation |
| `scripts/build_site.py` | static site generator |
| `scripts/heuristics.py` | AI-free classification (fallback + pre-annotation) |
| `scripts/make_fixture.py` | build a raw payload from a local clone (dev/offline) |
| `.github/workflows/monitor.yml` | the daily job |
| `.github/workflows/publish.yml` | build + deploy to Pages |
| `.github/workflows/validate.yml` | PR checks |

The seed edition (`data/analysis/2026-08-28.json`) was written by the assistant that
set this repository up, following the same `PROMPT.md` and schema Jules uses from the
next run on. `data/raw/2026-08-27.json` is deliberately left unreviewed so the
fallback rendering is visible.

Summaries are machine-written and can be wrong; the commit links are authoritative.
