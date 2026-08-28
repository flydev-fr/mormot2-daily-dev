# mORMot2 Daily

A daily, plain-English read of what changed in
[synopse/mORMot2](https://github.com/synopse/mORMot2) — for Delphi and FPC developers
who run mORMot2 in production and would rather drink their coffee than parse 30 terse
commit subjects.

Every morning a scheduled workflow pulls the new upstream commits with their diffs,
[Jules](https://jules.google) reviews the code and writes one structured JSON file,
that file is validated against a schema, and a static site is generated from it and
published to GitHub Pages.

```
                 fetch_commits.py            Jules REST API            build_site.py
synopse/mORMot2 ─────────────────► data/raw ──────────────► data/analysis ──────────► _site ──► Pages
                  commits+diffs      (JSON)     PR + schema     (JSON)      HTML/RSS/JSON
                                               validation
```

The reviewer never writes HTML. It writes JSON against
`schema/analysis.schema.json`, the JSON is contract-checked before it is merged, and
the site is generated deterministically from it — so a bad review can be wrong, but it
cannot break the page.

## What the site gives a reader

- **An edition per day**: a headline, a two-minute intro, a scannable TL;DR, and a
  risk level for a team running mORMot2 in production.
- **Entries grouped editorially** — breaking changes, security, fixes, new features,
  performance, compiler and platform, under the hood, tests, housekeeping — each with
  *what changed*, *what it means for you*, an action, and the public API moves.
- **Honesty markers**: `interpretation` when a claim is the reviewer's reading rather
  than something the commit states, `auto-classified` when an entry never got a
  review pass.
- Upstream build number (`2.4.16618`), diffstat, unit index, archive, activity chart,
  full-text filter, **RSS** (`feed.xml`) and **JSON** (`data.json`) feeds, light and
  dark themes.

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

## Caveats

Summaries are machine-written and can be wrong. The commit links are the source of
truth. 
