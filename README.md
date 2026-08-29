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

Type is two self-hosted faces, no external request:
[Lekton](https://fonts.google.com/specimen/Lekton) (ISIA Urbino, OFL) for
everything the generator computed — nav, labels, chips, counts, diffstats, SHAs,
unit names, and every description — and **Serrif**
([Displaay](https://displaay.net), licensed) for the titles only: the edition
headline, theme titles, page titles. Because the interface face is monospaced
there is no separate code stack and no third font file. Lekton has a 0.5 em
advance and a 0.475 em x-height, both small, so interface sizes are set about
8 % larger in `rem` than the same optical size would need elsewhere — change the
face and that scale has to move with it. Serrif defaults to Thin, so its
`@font-face` declares the full weight range or every title renders at 100. Swap
`--font-prose` / `--font-ui` at the top of `site/assets/style.css` to change them.

The page is not an article. An edition is a list of independent findings, so it
uses the full width — a sticky control rail beside a grid of entry cards that
reflows from one to three columns. `--shell` is the page, `--rail` the control
column, and `--measure` caps only the two places prose actually runs long (the
intro and the TL;DR).

## Audio editions

If `site/medias/` holds an episode for an edition, the masthead offers it. Two
names are recognised, in order:

| name | attached to |
|------|-------------|
| `<date>_<LANG>.m4a` | that edition, forever |
| `daily_<LANG>.m4a` | the newest edition only |

`daily_*` is the rolling file the generator overwrites each morning, so it is
deliberately not attached to older editions — tomorrow it is a different
recording, and yesterday's page would be offering audio that no longer matches
its text. Rename to `<date>_<LANG>.m4a` to keep an episode with its edition.

Where the page's language has no episode the English one is offered, labelled
with its language, the same fallback the prose uses. The player is a native
`<audio>` with `preload="none"`: nothing is fetched until the reader presses
play — verified, 0 audio requests on load.

> **Size.** These files are large: 42 MB and 31 MB today, 97 % of the built
> site. GitHub blocks files over 100 MB and warns over 50 MB, and every daily
> regeneration adds a new blob to git history even though the working tree
> keeps one copy — roughly 25 GB a year at this rate. Before this runs daily,
> the audio wants to live somewhere other than the repository: object storage,
> a GitHub Release, or the Render service, with `build_site.py` linking out to
> it instead of copying it in.

## Languages

The site is published in English, French, Chinese and Russian. English is
canonical and lives at the root; the others sit under `/fr/`, `/zh/` and `/ru/`
as complete trees, cross-linked with `hreflang` and a switcher in the masthead.
`assets/` and `data.json` are shared and stay at the root.

Two different things are translated. The **interface** — nav, column headings,
filter labels, severity and category names, dates, the About page — lives in
`scripts/i18n.py`. The **review** is written by the reviewer: every
reader-facing field in `data/analysis/<edition>.json` may be a plain string
(English) or an object keyed by language, and `en` is always required. Machine
fields — `sha`, `category`, `severity`, `action`, `units`, API symbols — are
never translated.

Where a translation is missing the English text is shown, the block carries
`lang="en"` so a screen reader does not read English with the page language's
phonetics, and an edition with no translation at all says so at the top. That
means older editions keep working unchanged: they are plain strings, and they
render as English inside a translated interface.

```bash
python scripts/build_site.py                 # all four languages
python scripts/build_site.py --langs en,fr   # a subset, while iterating
```

Adding a language means adding it to `LANGS` in `scripts/i18n.py` with its
string table, month and weekday names, and to the language list in `PROMPT.md`
so the reviewer writes it.

With a custom domain, set the `SITE_URL` repository variable to the canonical public
origin (e.g. `https://mormot2daily.fsb.dev`). `feed.xml` carries absolute links, and
the Pages output alone reports `http://` until *Enforce HTTPS* is provisioned and
keeps whatever domain was configured when the build ran.

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
