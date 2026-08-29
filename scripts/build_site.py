#!/usr/bin/env python3
"""Generate the static site from data/raw/*.json + data/analysis/*.json.

Deterministic: the same data always produces the same HTML. Jules never writes
markup — it only writes the analysis JSON that feeds this generator, so a bad
analysis run can degrade the content but can never break the layout.

    python scripts/build_site.py                # -> _site/
    python scripts/build_site.py --out /tmp/out --base-url https://x.github.io/y
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import pathlib
import re
import shutil
import sys
from dataclasses import dataclass, field

from common import (
    ANALYSIS_DIR, MEDIA_SRC, RAW_DIR, SITE_OUT, SITE_SRC, SITE_TAGLINE,
    SITE_TITLE, UPSTREAM,
    iso, parse_iso, read_json, short, utcnow,
)
from heuristics import classify
from i18n import (LANGS, LANG_NAMES, LANG_TAGS, S, long_date, prefix, tr,
                  tr_list)

# --------------------------------------------------------------------------- taxonomy

SECTIONS = [
    ("breaking", "Breaking changes"),
    ("security", "Security"),
    ("fix", "Fixes"),
    ("feature", "New features"),
    ("performance", "Performance"),
    ("compat", "Compiler & platform"),
    ("deprecation", "Deprecations"),
    ("refactor", "Under the hood"),
    ("tests", "Tests"),
    ("docs", "Docs"),
    ("chore", "Housekeeping"),
]
SECTION_ORDER = {key: i for i, (key, _label) in enumerate(SECTIONS)}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def section_title(key: str) -> str:
    return _(f"cat_{key}")


def severity_label(key: str) -> str:
    return _(f"sev_{key}")


def action_label(key: str) -> str:
    return _(f"act_{key}")


# Canonical public origin, set once by main() from --base-url. Only the tags that
# must carry an absolute URL use it (og:image); everything else stays relative so
# the output works when opened straight off disk.
BASE_URL = ""

# The language being generated. main() runs the whole page pipeline once per
# entry in LANGS, so every function below can read it without being threaded.
LANG = "en"

NEWLINE = chr(10)

# Placeholder swapped for the live-updating <span> after the sentence around it
# has been escaped, so the count can sit anywhere in a translated string.
SHOWN_SLOT = chr(1) + "shown" + chr(1)


def _(key: str, **fmt) -> str:
    """An interface string in the language being generated."""
    return S(LANG, key, **fmt)


def audio_duration(path: pathlib.Path) -> int:
    """Length in seconds from an MP4/M4A movie header, or 0 if unreadable.

    Read at build time so the page can say how long the episode is before a
    reader spends 40 MB finding out. Only the atom path to `mvhd` is walked —
    no decoding, no dependency.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return 0

    def atoms(off: int, end: int):
        while off + 8 <= end:
            size = int.from_bytes(data[off:off + 4], "big")
            kind = data[off + 4:off + 8].decode("latin-1", "replace")
            if size == 0:
                size = end - off
            if size < 8:
                return
            yield kind, off + 8, off + size
            off += size

    for kind, start, end in atoms(0, len(data)):
        if kind != "moov":
            continue
        for kind2, s2, _e2 in atoms(start, end):
            if kind2 != "mvhd":
                continue
            version = data[s2]
            if version == 0:
                scale = int.from_bytes(data[s2 + 12:s2 + 16], "big")
                length = int.from_bytes(data[s2 + 16:s2 + 20], "big")
            else:
                scale = int.from_bytes(data[s2 + 20:s2 + 24], "big")
                length = int.from_bytes(data[s2 + 24:s2 + 32], "big")
            return round(length / scale) if scale else 0
    return 0


def find_podcast(edition_date: str, lang: str, latest: bool) -> dict | None:
    """The audio edition for this date and language, if one exists.

    Two naming shapes are accepted. `<date>_<LANG>.m4a` belongs to one edition
    and stays correct forever, so it is preferred. `daily_<LANG>.m4a` is the
    rolling file the generator writes each morning; it is only attached to the
    newest edition, because tomorrow it will be a different recording and
    yesterday's page would then be lying about what it plays.
    """
    for name in (f"{edition_date}_{lang.upper()}.m4a",
                 f"daily_{lang.upper()}.m4a" if latest else ""):
        if not name:
            continue
        path = MEDIA_SRC / name
        if path.is_file():
            return {"file": name, "seconds": audio_duration(path),
                    "bytes": path.stat().st_size, "lang": lang}
    return None


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def words(*texts: str) -> int:
    return sum(len(re.findall(r"\S+", t or "")) for t in texts)


# ----------------------------------------------------------------------------- model

@dataclass
class Entry:
    sha: str
    headline: str
    category: str
    severity: str
    what_changed: str
    impact: str
    action: str
    action_detail: str = ""
    units: list[str] = field(default_factory=list)
    api_changes: list[dict] = field(default_factory=list)
    confidence: str = "interpretation"
    reviewed: bool = True
    # from the raw payload
    subject: str = ""
    author: str = ""
    date: str = ""
    url: str = ""
    additions: int = 0
    deletions: int = 0
    files: list[dict] = field(default_factory=list)
    pr: int | None = None
    areas: list[str] = field(default_factory=list)

    @property
    def sort_key(self):
        return (SEVERITY_ORDER.get(self.severity, 9), SECTION_ORDER.get(self.category, 99),
                -(self.additions + self.deletions))


@dataclass
class Edition:
    date: str
    title: str
    intro: str
    tldr: list[str]
    risk: str
    upgrade_advice: str
    notes: str
    themes: list[dict]
    entries: list[Entry]
    reviewed: bool
    version: dict
    totals: dict
    generated_at: str
    lang: str = "en"
    content_lang: str = "en"
    # Reviewer fields that fell back to English on this page, so each can
    # say so even when the edition as a whole counts as translated.
    fallbacks: set = field(default_factory=set)

    @property
    def translated(self) -> bool:
        """Is the reviewer's prose in the page's own language?"""
        return self.content_lang == self.lang

    def field_attr(self, name: str) -> str:
        """lang="en" for a field that fell back on its own."""
        return ' lang="en"' if name in self.fallbacks else ""

    @property
    def pretty_date(self) -> str:
        return long_date(parse_iso(self.date + "T00:00:00Z").date(), self.lang)

    @property
    def read_minutes(self) -> int:
        count = words(self.intro, *self.tldr,
                      *[e.what_changed for e in self.entries],
                      *[e.impact for e in self.entries])
        return max(1, round(count / 220))

    @property
    def counts(self) -> dict:
        out: dict[str, int] = {}
        for entry in self.entries:
            out[entry.category] = out.get(entry.category, 0) + 1
        return out

    @property
    def top_severity(self) -> str:
        return min((e.severity for e in self.entries),
                   key=lambda s: SEVERITY_ORDER.get(s, 9), default="low")

    def sections(self) -> list[tuple[str, str, list[Entry]]]:
        out = []
        for key, title in SECTIONS:
            bucket = sorted([e for e in self.entries if e.category == key],
                            key=lambda e: e.sort_key)
            if bucket:
                out.append((key, title, bucket))
        return out


def load_editions(lang: str = "en") -> list[Edition]:
    dates = sorted({p.stem for p in RAW_DIR.glob("*.json")} |
                   {p.stem for p in ANALYSIS_DIR.glob("*.json")}, reverse=True)
    editions = []
    for date in dates:
        raw = read_json(RAW_DIR / f"{date}.json", {}) or {}
        analysis = read_json(ANALYSIS_DIR / f"{date}.json", {}) or {}
        editions.append(build_edition(date, raw, analysis, lang))
    return editions


def build_edition(date: str, raw: dict, analysis: dict,
                  lang: str = "en") -> Edition:
    commits = {c["sha"]: c for c in raw.get("commits", [])}
    by_short = {sha[:8]: sha for sha in commits}
    reviewed = bool(analysis.get("entries"))
    entries: list[Entry] = []
    seen: set[str] = set()

    for item in analysis.get("entries", []) or []:
        sha = item.get("sha", "")
        full = sha if sha in commits else by_short.get(sha[:8], sha)
        commit = commits.get(full, {})
        seen.add(full)
        entries.append(_entry(item, commit, reviewed=True, lang=lang))

    # Commits with no analysis entry still show up, flagged as unreviewed.
    for sha, commit in commits.items():
        if sha in seen or commit.get("is_merge"):
            continue
        guess = commit.get("guess") or classify(commit.get("subject", ""),
                                                commit.get("body", ""))
        entries.append(_entry({
            "sha": sha,
            "headline": commit.get("subject", "(no subject)"),
            "category": guess.get("category", "chore"),
            "severity": guess.get("severity", "low"),
            "what_changed": commit.get("body") or "",
            "impact": "",
            "action": "none",
            "confidence": "interpretation",
        }, commit, reviewed=False, lang=lang))

    entries.sort(key=lambda e: e.sort_key)
    count = len(commits)
    fallback_title = ("A quiet day upstream" if count == 0
                      else f"{count} commit{'s' if count != 1 else ''} landed upstream")
    fallback_intro = (
        "No commits in this window."
        if count == 0 else
        "This edition has not been reviewed yet: the entries below are classified "
        "automatically from commit messages and diffs, without an editorial pass. "
        "Treat the categories as hints and follow the commit links for the truth.")

    # The reviewer may have written this edition in some languages and not
    # others. edition_title stands for the lot: if it is not translated the
    # page says so and marks the prose lang="en".
    title, content_lang = tr(analysis.get("edition_title"), lang)
    fallbacks = {name for name in ("intro", "upgrade_advice", "notes")
                 if analysis.get(name) and tr(analysis[name], lang)[1] != lang}
    themes = [{**t,
               "title": tr(t.get("title"), lang)[0],
               "summary": tr(t.get("summary"), lang)[0]}
              for t in (analysis.get("themes") or [])]

    return Edition(
        date=date,
        title=title or fallback_title,
        intro=tr(analysis.get("intro"), lang)[0] or fallback_intro,
        tldr=tr_list(analysis.get("tldr"), lang)[0],
        risk=analysis.get("risk_level") or ("calm" if count == 0 else ""),
        upgrade_advice=tr(analysis.get("upgrade_advice"), lang)[0],
        notes=tr(analysis.get("notes"), lang)[0],
        themes=themes,
        lang=lang,
        content_lang=content_lang if analysis else lang,
        fallbacks=fallbacks,
        entries=entries,
        reviewed=reviewed,
        version=raw.get("version") or {},
        totals=raw.get("totals") or {"commits": count, "additions": 0, "deletions": 0},
        generated_at=raw.get("generated_at") or "",
    )


def _entry(item: dict, commit: dict, reviewed: bool, lang: str = "en") -> Entry:
    stats = commit.get("stats", {}) or {}
    units = item.get("units") or commit.get("units") or []
    return Entry(
        sha=commit.get("sha") or item.get("sha", ""),
        headline=tr(item.get("headline"), lang)[0] or commit.get("subject", ""),
        category=item.get("category", "chore"),
        severity=item.get("severity", "low"),
        what_changed=tr(item.get("what_changed"), lang)[0],
        impact=tr(item.get("impact"), lang)[0],
        action=item.get("action", "none"),
        action_detail=tr(item.get("action_detail"), lang)[0],
        units=units,
        api_changes=[{**c, "note": tr(c.get("note"), lang)[0]}
                     for c in (item.get("api_changes") or [])],
        confidence=item.get("confidence", "interpretation"),
        reviewed=reviewed,
        subject=commit.get("subject", ""),
        author=commit.get("author", ""),
        date=commit.get("date", ""),
        url=commit.get("url", ""),
        additions=stats.get("additions", 0),
        deletions=stats.get("deletions", 0),
        files=[f for f in commit.get("files", []) if f.get("patch") is not None],
        pr=commit.get("pr"),
        areas=commit.get("areas") or [],
    )


# ------------------------------------------------------------------------ components

def chip(text: str, kind: str = "", title: str = "") -> str:
    attrs = f' title="{esc(title)}"' if title else ""
    return f'<span class="chip {esc(kind)}"{attrs}>{esc(text)}</span>'


def severity_chip(severity: str) -> str:
    label = severity_label(severity)
    return (f'<span class="sev sev-{esc(severity)}" title="Severity: {esc(label)}">'
            f'<span class="dot" aria-hidden="true"></span>{esc(label)}</span>')


def action_badge(entry: Entry) -> str:
    if entry.action == "none":
        return ""
    detail = f'<p class="action-detail">{esc(entry.action_detail)}</p>' if entry.action_detail else ""
    return (f'<div class="action action-{esc(entry.action)}">'
            f'<span class="action-label">{esc(action_label(entry.action))}</span>'
            f'{detail}</div>')


def entry_row(entry: Entry, index: int, base: str = "",
              themes: str = "") -> str:
    """One commit as a table row that opens.

    The digest is a list of independent findings, so it reads as a dense sortable
    table rather than a column of cards: the closed row carries what a reader
    scans by (severity, size, headline, category, units, commit) and everything
    that needs prose — impact, the action, the public API moves — is one click
    away. The full text stays in the DOM either way so search still reaches it.
    """
    units = "".join(f'<span class="chip unit">{esc(u)}</span>'
                    for u in entry.units[:1])
    if len(entry.units) > 1:
        units += f'<span class="chip chip-rest">+{len(entry.units) - 1}</span>'

    flags = ""
    if not entry.reviewed:
        flags = ('<span class="chip warn" title="Classified automatically from the '
                 'commit message and diff — no editorial pass">auto</span>')
    elif entry.confidence == "interpretation":
        flags = ('<span class="chip soft" title="The reviewer&#39;s reading of '
                 'the consequences, not something the commit states">interp</span>')

    # Detail panel — only the parts this entry actually has.
    detail = []
    if entry.subject and entry.subject.strip().lower() != entry.headline.strip().lower():
        detail.append(f'<p class="d-subject"><code>{esc(entry.subject)}</code></p>')
    if entry.impact:
        detail.append(f'<div class="d-block d-impact"><h4>{esc(_("impact"))}</h4>'
                      f'<p>{esc(entry.impact)}</p></div>')
    if entry.action != "none":
        note = (f'<p>{esc(entry.action_detail)}</p>' if entry.action_detail else "")
        detail.append(f'<div class="d-block d-action action-{esc(entry.action)}">'
                      f'<h4>{esc(action_label(entry.action))}</h4>'
                      f'{note}</div>')
    if entry.api_changes:
        rows = "".join(
            f'<li><code>{esc(c.get("symbol", ""))}</code>'
            f'<span class="api-kind">{esc(c.get("change", ""))}</span>'
            f'{" — " + esc(c.get("note")) if c.get("note") else ""}</li>'
            for c in entry.api_changes)
        detail.append(f'<div class="d-block"><h4>{esc(_("public_api"))}</h4><ul>{rows}</ul></div>')
    if entry.units:
        all_units = " ".join(
            f'<a class="chip unit" href="{base}units.html#{esc(u)}">{esc(u)}</a>'
            for u in entry.units)
        detail.append(f'<div class="d-block"><h4>{esc(_("col_units"))}</h4>'
                      f'<div class="units">{all_units}</div></div>')
    meta = " · ".join(x for x in (
        esc(entry.author),
        parse_iso(entry.date).strftime("%H:%M UTC") if entry.date else "",
        f'PR #{entry.pr}' if entry.pr else "") if x)
    detail.append(f'<p class="d-meta">{meta} · '
                  f'<a href="{esc(entry.url)}">{esc(_('view_commit'))}</a></p>')

    # The diffstat rides the commit column rather than owning one: it is useful
    # context, not something a reader scans by, and its 5.2rem went to the entry
    # and category columns, which were the ones actually short of room.
    lines = ""
    if entry.additions or entry.deletions:
        lines = (f'<span class="c-lines"><span class="add">+{entry.additions}</span>'
                 f'<span class="del">-{entry.deletions}</span></span>')

    return f"""
<details class="row" id="c-{esc(short(entry.sha))}"
         data-category="{esc(entry.category)}" data-severity="{esc(entry.severity)}"
         data-weight="{entry.additions + entry.deletions}"
         data-rank="{SEVERITY_ORDER.get(entry.severity, 9)}"
         data-themes="{themes}"
         data-action="{'yes' if entry.action != 'none' else 'no'}"
         data-reviewed="{'yes' if entry.reviewed else 'no'}"
         data-search="{esc((entry.headline + ' ' + entry.subject + ' ' +
                            ' '.join(entry.units) + ' ' + entry.what_changed + ' ' +
                            entry.impact).lower())}">
  <summary>
    <span class="c-n">{index}</span>
    <span class="c-sev sev-{esc(entry.severity)}"><i class="sev-bar"></i>
      {esc(severity_label(entry.severity))}</span>
    <span class="c-name"><strong>{esc(entry.headline)}</strong>
      <em>{esc(entry.what_changed)}</em></span>
    <span class="c-cat">{chip(section_title(entry.category),
                              'cat cat-' + entry.category)}{flags}</span>
    <span class="c-units">{units}</span>
    <span class="c-commit"><code>{esc(short(entry.sha))}</code>{lines}</span>
    <span class="c-open" aria-hidden="true"></span>
  </summary>
  <div class="row-detail">{"".join(detail)}</div>
</details>"""


def activity_chart(editions: list[Edition], days: int = 30, *,
                   band: bool = False, base: str = "") -> str:
    """Commits per day — one series, one hue, direct labels on the extremes.

    As a `band` it runs the full width between the masthead and the entries: the
    one horizontal element on a page built from columns, which is what stops the
    grid reading as an undifferentiated stack. It gets real height there — a
    60-day series drawn 38px tall is decoration pretending to be data.
    """
    today = utcnow().date()
    series = []
    by_date = {e.date: e for e in editions}
    for offset in range(days - 1, -1, -1):
        day = today - dt.timedelta(days=offset)
        key = day.isoformat()
        edition = by_date.get(key)
        series.append((key, edition.totals.get("commits", 0) if edition else 0,
                       bool(edition)))
    peak = max((v for _, v, _ in series), default=0) or 1

    width, height, gap = 100.0, 34.0, 0.6
    bar_w = (width - gap * (len(series) - 1)) / len(series)
    bars = []
    for i, (key, value, exists) in enumerate(series):
        h = (value / peak) * height if value else 0.8
        x = i * (bar_w + gap)
        y = height - h
        cls = "bar" if value else "bar bar-empty"
        href = f'{base}edition/{key}.html' if exists else ""
        label = f"{key}: {value} commit{'s' if value != 1 else ''}"
        rect = (f'<rect class="{cls}" x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" '
                f'height="{max(h, 0.8):.2f}"><title>{esc(label)}</title></rect>')
        bars.append(f'<a href="{href}">{rect}</a>' if href else rect)

    first, last = series[0][0], series[-1][0]
    # Month boundaries as timeline ticks — the marker that tells the reader what
    # the horizontal axis actually spans.
    ticks = "".join(
        f'<rect class="tick" x="{i * (bar_w + gap):.2f}" y="0" width="0.12" '
        f'height="{height:.2f}"></rect>'
        for i, (key, _, _) in enumerate(series) if key.endswith("-01"))

    # A sparse window is mostly empty bars, and empty bars say nothing. The
    # figures beside them carry the reading the shape alone cannot.
    total = sum(v for _, v, _ in series)
    active = sum(1 for _, v, _ in series if v)
    busiest = max(series, key=lambda r: r[1])[0] if total else "—"
    stats = "".join(
        f'<div class="stat"><span class="k">{k}</span><span class="v">{v}</span></div>'
        for k, v in ((_("stat_commits"), total),
                     (_("stat_active"), f"{active}/{days}"),
                     (_("stat_busiest"), busiest), (_("stat_peak"), peak)))

    return f"""
<figure class="chart{' chart-band' if band else ''}">
  <figcaption>
    <span class="chart-title">{esc(_("activity"))}</span>
    <span class="chart-note">{esc(_("activity_note", days=days))}</span>
  </figcaption>
  <div class="chart-stats">{stats}</div>
  <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img"
       aria-label="{esc(_("activity_aria", days=days, peak=peak))}">
    {ticks}{"".join(bars)}
  </svg>
  <div class="chart-axis"><span>{esc(first)}</span><span>{esc(last)}</span></div>
</figure>"""


# ----------------------------------------------------------------------------- pages

def layout(title: str, body: str, *, description: str, base: str = "",
           extra_head: str = "", nav_active: str = "",
           page_path: str = "index.html") -> str:
    """Wrap a page.

    Two prefixes are in play. `base` walks up inside one language tree, exactly
    as it did when the site had one language — /fr/edition/X.html links to its
    own /fr/index.html. `root` walks all the way out to the site root, where the
    single shared copy of assets/ lives and where the other language trees are.
    """
    root = base + ("" if LANG == "en" else "../")

    def nav(href: str, label: str, key: str) -> str:
        active = ' class="active"' if key == nav_active else ""
        return f'<a href="{base}{href}"{active}>{label}</a>'

    # og:image is the one tag a crawler will not resolve relatively — emit it
    # only when we actually know the public origin.
    og_image = (f'<meta property="og:image" '
                f'content="{BASE_URL}/assets/android-chrome-512x512.png">' + NEWLINE
                if BASE_URL else "")

    alternates = NEWLINE.join(
        f'<link rel="alternate" hreflang="{LANG_TAGS[l]}" '
        f'href="{root}{prefix(l)}{page_path}">' for l in LANGS)
    alternates += (NEWLINE + f'<link rel="alternate" hreflang="x-default" href="{root}{page_path}">')

    # A disclosure, not a <select>: the options stay real links, so they work
    # without scripting and a crawler can follow them to the hreflang targets.
    # Only text goes in the <summary> — a link there would not be reliably
    # focusable, which is the rule the entry rows already follow.
    options = "".join(
        f'<a href="{root}{prefix(l)}{page_path}" hreflang="{LANG_TAGS[l]}"'
        + (' aria-current="true"' if l == LANG else "")
        + f'>{LANG_NAMES[l]}</a>'
        for l in LANGS)
    switcher = (f'<details class="langs"><summary>'
                f'<span class="sr">{esc(_("lang_aria"))}: </span>'
                f'{LANG_NAMES[LANG]}</summary>'
                f'<div class="lang-menu">{options}</div></details>')

    return f"""<!doctype html>
<html lang="{LANG_TAGS[LANG]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:locale" content="{LANG_TAGS[LANG]}">
{og_image}<meta property="og:type" content="website">
<meta name="theme-color" content="#fafafa" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0d0d" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{root}assets/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="{root}assets/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="16x16" href="{root}assets/favicon-16x16.png">
<link rel="apple-touch-icon" href="{root}assets/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="{esc(SITE_TITLE)}" href="{base}feed.xml">
{alternates}
<link rel="preload" as="font" type="font/woff" href="{root}assets/fonts/Lekton-Regular.woff" crossorigin>
<link rel="preload" as="font" type="font/woff2" href="{root}assets/fonts/SerrifVF.woff2" crossorigin>
<link rel="stylesheet" href="{root}assets/style.css">
{extra_head}
</head>
<body>
<a class="skip" href="#main">{esc(_('skip'))}</a>
<header class="site">
  <div class="wrap">
    <a class="brand" href="{base}index.html">
      <img class="brand-mark" src="{root}assets/mormotsaurus.png" alt=""
           width="30" height="30" decoding="async">
      <span><strong>{esc(SITE_TITLE)}</strong><em>{esc(_('tagline'))}</em></span>
    </a>
    <nav>
      {nav('index.html', esc(_('nav_today')), 'today')}
      {nav('archive.html', esc(_('nav_archive')), 'archive')}
      {nav('units.html', esc(_('nav_units')), 'units')}
      {nav('about.html', esc(_('nav_about')), 'about')}
      <a href="https://github.com/{UPSTREAM}" rel="noopener">{esc(_('nav_upstream'))}</a>
      {switcher}
      <button id="theme" type="button" aria-label="{esc(_('theme_aria'))}">
        <span class="theme-icon" aria-hidden="true"></span>
      </button>
    </nav>
  </div>
</header>
<main id="main" class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p><a href="https://github.com/{UPSTREAM}">{UPSTREAM}</a> ·
       {esc(_('footer_note'))} ·
       {esc(_('footer_built'))} {esc(iso(utcnow()))} ·
       <a href="{base}feed.xml">RSS</a> · <a href="{root}data.json">JSON</a></p>
  </div>
</footer>
<script src="{root}assets/app.js"></script>
</body>
</html>
"""


def root_from(base: str) -> str:
    """Site root from a page, given its in-tree base. Media is shared, like assets."""
    return base + ("" if LANG == "en" else "../")


def edition_header(edition: Edition, base: str, *, permalink: bool,
                   editions: list[Edition] | None = None,
                   latest: bool = False) -> str:
    # The risk verdict rides on the dateline instead of owning a block below the
    # intro: date and "do I have to care today?" are the two things a reader
    # wants above the fold, and together they cost one line instead of four.
    risk_html = ""
    if edition.risk:
        risk_html = (f'<span class="risk-flag risk-{esc(edition.risk)}">'
                     f'{esc(_("risk_" + edition.risk))}'
                     f'<span class="why">{esc(_("why_" + edition.risk))}</span>'
                     f'</span>')
    version = edition.version or {}
    facts = []
    if version.get("after"):
        before = version.get("before")
        facts.append(f'<div class="fact"><span class="k">{esc(_("fact_build"))}</span>'
                     f'<span class="v">{esc(before + " → " if before else "")}'
                     f'{esc(version["after"])}</span></div>')
    facts.append(f'<div class="fact"><span class="k">{esc(_("fact_commits"))}</span>'
                 f'<span class="v">{edition.totals.get("commits", 0)}</span></div>')
    facts.append(f'<div class="fact"><span class="k">{esc(_("fact_lines"))}</span>'
                 f'<span class="v"><span class="add">+{edition.totals.get("additions", 0)}</span> '
                 f'<span class="del">-{edition.totals.get("deletions", 0)}</span></span></div>')
    facts.append(f'<div class="fact"><span class="k">{esc(_("fact_read"))}</span>'
                 f'<span class="v">{esc(_('read_min', n=edition.read_minutes))}</span></div>')

    title = esc(edition.title)
    if permalink:
        title = f'<a href="{base}edition/{edition.date}.html">{title}</a>'
    tldr = ""
    if edition.tldr:
        items = "".join(f"<li>{esc(item)}</li>" for item in edition.tldr)
        tldr = f'<div class="tldr"><h2>{esc(_("tldr"))}</h2><ul>{items}</ul></div>'
    banner = ("" if edition.reviewed else
              f'<p class="banner">{esc(_("banner_unreviewed"))}</p>')

    # Left column is the day in words — headline, intro, takeaways. Right column
    # is what to do about it and how the day sits against the ones before it.
    # The reviewer's notes are usually one sentence about the run itself, which
    # is not worth a block of its own. It rides the dateline as an indicator and
    # opens on hover or focus — CSS only, so it works with scripting off.
    notes_html = ""
    if edition.notes:
        # Inline SVG: no request, and it inherits currentColor with the dateline.
        icon = ('<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" '
                'fill="none" stroke="currentColor" stroke-width="1.3">'
                '<circle cx="8" cy="8" r="6.5"/>'
                '<path d="M8 7.1v4.1" stroke-linecap="round"/>'
                '<path d="M8 4.6h.01" stroke-linecap="round" stroke-width="1.7"/>'
                '</svg>')
        notes_html = (
            f'<span class="note-flag" tabindex="0" aria-describedby="edition-notes" '
            f'aria-label="Notes from the reviewer">{icon}'
            f'<span class="note-pop" role="tooltip" id="edition-notes">'
            f'{esc(edition.notes)}</span></span>')

    # Audio edition, if the generator produced one. Falls back to English the
    # way the prose does, and says which language it is in when it differs.
    cast = (find_podcast(edition.date, LANG, latest)
            or find_podcast(edition.date, "en", latest))
    player = ""
    if cast:
        src = f'{root_from(base)}medias/{cast["file"]}'
        meta = _("listen_meta", mins=max(1, round(cast["seconds"] / 60)),
                 mb=round(cast["bytes"] / 1024 / 1024))
        note = ("" if cast["lang"] == LANG else
                f' · {esc(_("listen_in", language=LANG_NAMES[cast["lang"]]))}')
        player = (
            f'<div class="podcast">'
            f'<div class="podcast-head">'
            f'<span class="podcast-title">{esc(_("listen"))}</span>'
            f'<span class="podcast-meta">{esc(meta)}{note} · '
            f'<a href="{src}" download>{esc(_("listen_dl"))}</a></span></div>'
            # preload="none": the file is tens of megabytes, and nobody should
            # pay for it just by opening the page.
            f'<audio controls preload="none" src="{src}"'
            f' lang="{LANG_TAGS[cast["lang"]]}"></audio></div>')

    advice = ""
    if edition.upgrade_advice:
        advice = (f'<section class="advice"><h2>{esc(_("upgrade_advice"))}</h2>'
                  f'<p>{esc(edition.upgrade_advice)}</p></section>')

    # A page in another language showing English prose must declare it, or a
    # screen reader pronounces English with the page language's phonetics.
    content_attr = "" if edition.translated else f' lang="{LANG_TAGS["en"]}"'
    notice = ("" if edition.translated else
              f'<p class="banner untranslated">{esc(_("untranslated"))}</p>')

    return f"""
<section class="edition-head"{content_attr}>
  <p class="dateline">
    <time datetime="{esc(edition.date)}">{esc(edition.pretty_date)}</time>
    {risk_html}{notes_html}
  </p>
  <div class="head-grid">
    <div class="head-main">
      <h1>{title}</h1>
      {notice}{banner}
      <p class="intro">{esc(edition.intro)}</p>
    </div>
    <div class="head-side">{tldr}{player}</div>
  </div>
  {advice}
  <div class="facts">{"".join(facts)}</div>
</section>"""


def theme_index(edition: Edition) -> dict[str, list[int]]:
    """Short SHA -> the themes it belongs to.

    A theme's only irreplaceable content is its list of commits: its summary is
    close to a longer TL;DR bullet, but nothing else on the page can say "these
    five rows are one story". So themes drive a filter rather than a card.
    """
    out: dict[str, list[int]] = {}
    for i, theme in enumerate(edition.themes or []):
        for sha in theme.get("shas", []):
            out.setdefault(short(sha), []).append(i)
    return out


def theme_filters(edition: Edition) -> tuple[str, str]:
    themes = edition.themes or []
    if not themes:
        return "", ""
    index = theme_index(edition)
    chips, summaries = [], []
    for i, theme in enumerate(themes):
        count = sum(1 for v in index.values() if i in v)
        chips.append(
            f'<button class="theme-chip" data-theme="{i}" aria-pressed="false">'
            f'<span class="t">{esc(theme.get("title", ""))}</span>'
            f'<span class="n">{count}</span></button>')
        summaries.append(
            f'<div class="theme-summary hidden" data-theme="{i}">'
            f'<span class="s-label">{esc(theme.get("title", ""))}</span>'
            f'<p>{esc(theme.get("summary", ""))}</p></div>')
    return (f'<div class="themes-row"><span class="themes-label">{esc(_('stories'))}</span>'
            f'{"".join(chips)}</div>', "".join(summaries))


def filters_bar(edition: Edition) -> str:
    """Search, category and severity filters in one panel above the table."""
    chips, summaries = theme_filters(edition)
    counts = edition.counts
    cats = "".join(
        f'<option value="{esc(key)}">{esc(title)} ({counts[key]})</option>'
        for key, title in SECTIONS if counts.get(key))
    sev_counts: dict[str, int] = {}
    for e in edition.entries:
        sev_counts[e.severity] = sev_counts.get(e.severity, 0) + 1
    sevs = "".join(
        f'<option value="{esc(k)}">{esc(severity_label(k))} ({sev_counts[k]})</option>'
        for k in ("critical", "high", "medium", "low") if sev_counts.get(k))
    return f"""
<div class="toolbar">
  <label class="search"><span class="sr">{esc(_("search_label"))}</span>
    <input type="search" id="q" placeholder="{esc(_('search_placeholder'))}"></label>
  <label class="select"><span class="sr">{esc(_("label_category"))}</span>
    <select id="f-cat"><option value="">{esc(_("all_categories"))}</option>{cats}</select></label>
  <label class="select"><span class="sr">{esc(_("label_severity"))}</span>
    <select id="f-sev"><option value="">{esc(_("all_severities"))}</option>{sevs}</select></label>
  <button class="toggle" id="t-action" type="button" aria-pressed="false">{esc(_("action_needed"))}</button>
  <button class="toggle" id="t-review" type="button" aria-pressed="false">{esc(_("reviewed_only"))}</button>
  {chips}
</div>{summaries}"""


def entry_table(edition: Edition, base: str = "") -> str:
    """Every entry in one table, severity first — no per-category sections.

    Grouping into eleven category sections left most of them holding a single
    entry, which wasted the width the table exists to use. Category became a
    column and a filter instead: the same information, one list.
    """
    table_attr = "" if edition.translated else f' lang="{LANG_TAGS["en"]}"'
    index = theme_index(edition)
    rows = "".join(
        entry_row(e, i, base, ",".join(str(t) for t in index.get(short(e.sha), [])))
        for i, e in enumerate(sorted(edition.entries,
                                     key=lambda e: e.sort_key), start=1))
    return f"""
<div class="table" id="entries"{table_attr}>
  <div class="thead">
    <span class="c-n">#</span>
    <button class="c-sev sort" data-sort="rank" aria-pressed="true">{esc(_("label_severity"))}</button>
    <span class="c-name">{esc(_("col_entry"))}</span>
    <span class="c-cat">{esc(_("label_category"))}</span>
    <span class="c-units">{esc(_("col_units"))}</span>
    <button class="c-commit sort" data-sort="weight" aria-pressed="false"
            title="{esc(_('sort_by_size'))}">{esc(_("col_commit"))}</button>
    <span class="c-open"></span>
  </div>
  {rows}
  <p class="no-hits hidden">{esc(_("no_hits"))}</p>
</div>"""


def edition_body(edition: Edition, base: str,
                 editions: list[Edition] | None = None) -> str:
    """The edition below the masthead.

    An edition is a list of independent findings, so it reads as one dense table
    under a filter panel rather than a column of cards down a narrow measure.
    Themes follow the table: they are the narrative around the findings, not the
    findings, and putting them first pushed the entries most of a screen down.
    """
    if not edition.entries:
        return ('<section class="empty"><h2>{esc(_("empty_title"))}</h2>'
                f'<p>{esc(_("empty_body"))}</p></section>')
    total = len(edition.entries)
    parts = [
        f'<p class="result-count">'
        + esc(_("count_line", shown=SHOWN_SLOT, total=total,
                commits=edition.totals.get("commits", 0)))
          .replace(SHOWN_SLOT, f'<span id="shown">{total}</span>')
        + '</p>',
        filters_bar(edition),
        entry_table(edition, base),
    ]

    # All that follows the table is the narrative: the themes.
    # Activity is cosmetic — context for someone who has already read the day,
    # so it closes the page at full width instead of taking a masthead column.
    parts.append(signals_block(editions, base))
    return "".join(parts)


def signals_block(editions: list[Edition] | None, base: str = "") -> str:
    """Upstream activity, directly under the facts strip.

    It used to sit between the masthead and the first entry, putting a figure in
    front of the reader before a single sentence of the review. It is context for
    someone already reading — the dateline answers "do I have to care today?".
    """
    if not editions:
        return ""
    return (f'<section class="signals">'
            f'{activity_chart(editions, 60, base=base)}</section>')


def page_index(editions: list[Edition]) -> str:
    latest = editions[0]
    older = editions[1:13]
    archive = "".join(
        f'<li><a href="edition/{e.date}.html"><time>{esc(e.date)}</time>'
        f'<span class="t">{esc(e.title)}</span>'
        f'<span class="n">{e.totals.get("commits", 0)}</span></a></li>' for e in older)
    more = (f'<p class="more"><a href="archive.html">{esc(_("all_editions"))}</a></p>'
            if len(editions) > 13 else "")
    body = f"""
{edition_header(latest, "", permalink=True, editions=editions, latest=True)}
{edition_body(latest, "", editions)}
<section class="archive-preview">
  <h2>{esc(_("earlier"))}</h2>
  <ul class="archive-list">{archive}</ul>
  {more}
</section>"""
    return layout(f"{SITE_TITLE} — {latest.title}", body,
                  description=latest.intro[:180], nav_active="today",
                  page_path="index.html")


def page_edition(edition: Edition, prev: Edition | None, nxt: Edition | None,
                 all_editions: list[Edition] | None = None) -> str:
    nav = []
    if nxt:
        nav.append(f'<a class="prevnext" href="{nxt.date}.html">← {esc(nxt.date)}</a>')
    if prev:
        nav.append(f'<a class="prevnext right" href="{prev.date}.html">{esc(prev.date)} →</a>')
    body = (edition_header(edition, "../", permalink=False,
                           editions=all_editions,
                           latest=bool(all_editions) and edition is all_editions[0])
            + edition_body(edition, "../", all_editions)
            + f'<nav class="pager">{"".join(nav)}</nav>')
    return layout(f"{SITE_TITLE} — {edition.date}", body,
                  description=edition.intro[:180], base="../", nav_active="",
                  page_path=f"edition/{edition.date}.html")


def page_archive(editions: list[Edition]) -> str:
    rows = []
    for edition in editions:
        badges = "".join(chip(section_title(k), "cat cat-" + k)
                         for k in ("breaking", "security", "feature")
                         if edition.counts.get(k))
        rows.append(
            f'<tr><td><a href="edition/{edition.date}.html">{esc(edition.date)}</a></td>'
            f'<td class="title">{esc(edition.title)} {badges}</td>'
            f'<td class="num">{edition.totals.get("commits", 0)}</td>'
            f'<td>{severity_chip(edition.top_severity)}</td></tr>')
    body = f"""
<section class="page-head"><h1>{esc(_('archive_title'))}</h1>
  <p>{esc(_('archive_count', n=len(editions)))}</p></section>
{activity_chart(editions, 60, band=True)}
<table class="archive-table">
  <thead><tr><th>{esc(_('th_date'))}</th><th>{esc(_('th_edition'))}</th>
    <th class="num">{esc(_('th_commits'))}</th>
    <th>{esc(_('th_top_severity'))}</th></tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>"""
    return layout(f"{SITE_TITLE} — {_('archive_title')}", body,
                  description=_("archive_count", n=len(editions)),
                  nav_active="archive", page_path="archive.html")


def page_units(editions: list[Edition]) -> str:
    index: dict[str, list[tuple[str, Entry]]] = {}
    for edition in editions:
        for entry in edition.entries:
            for unit in entry.units:
                index.setdefault(unit, []).append((edition.date, entry))
    if not index:
        body = (f'<section class="page-head"><h1>{esc(_("units_title"))}</h1>'
                f'<p>{esc(_("units_empty"))}</p></section>')
        return layout(f"{SITE_TITLE} — {_('units_title')}", body,
                      description=_("units_empty"), nav_active="units",
                      page_path="units.html")

    groups: dict[str, list[str]] = {}
    for unit in index:
        family = ".".join(unit.split(".")[:2]) if unit.count(".") >= 2 else unit
        groups.setdefault(family, []).append(unit)

    blocks = []
    for family in sorted(groups):
        items = []
        for unit in sorted(groups[family]):
            hits = index[unit]
            recent = "".join(
                f'<li><a href="edition/{date}.html#c-{esc(short(entry.sha))}">'
                f'<time>{esc(date)}</time> {esc(entry.headline)}</a></li>'
                for date, entry in hits[:6])
            items.append(
                f'<details id="{esc(unit)}" class="unit-block">'
                f'<summary><code>{esc(unit)}</code>'
                f'<span class="n">{len(hits)}</span></summary>'
                f'<ul>{recent}</ul></details>')
        blocks.append(f'<section class="unit-family"><h2><code>{esc(family)}</code></h2>'
                      f'{"".join(items)}</section>')

    body = f"""
<section class="page-head"><h1>{esc(_('units_title'))}</h1>
  <p>{esc(_('units_count', n=len(index)))}</p></section>
{"".join(blocks)}"""
    return layout(f"{SITE_TITLE} — {_('units_title')}", body,
                  description=_("units_count", n=len(index)),
                  nav_active="units", page_path="units.html")


def page_about() -> str:
    root = "" if LANG == "en" else "../"
    repo = f'<a href="https://github.com/{UPSTREAM}">{UPSTREAM}</a>'
    lekton = '<a href="https://fonts.google.com/specimen/Lekton">Lekton</a>'
    serrif = '<em>Serrif</em> (<a href="https://displaay.net">Displaay</a>)'
    body = f"""
<section class="page-head"><h1>{esc(_('about_title'))}</h1></section>
<section class="prose">
  <h2>{esc(_('about_pipeline'))}</h2>
  <ol>
    <li>{_('about_p1', repo=repo)}</li>
    <li>{esc(_('about_p2'))}</li>
    <li>{esc(_('about_p3'))}</li>
    <li>{esc(_('about_p4'))}</li>
    <li>{esc(_('about_p5'))}</li>
  </ol>

  <h2>{esc(_('about_markers'))}</h2>
  <ul>
    <li><em>{esc(_('chip_interp'))}</em> — {esc(_('about_m1'))}</li>
    <li><em>{esc(_('chip_auto'))}</em> — {esc(_('about_m2'))}</li>
    <li><em>{esc(_('label_severity')).lower()}</em> — {esc(_('about_m3'))}</li>
  </ul>

  <h2>{esc(_('about_type'))}</h2>
  <p>{_('about_type_body', lekton=lekton, serrif=serrif)}</p>

  <h2>{esc(_('about_lang'))}</h2>
  <p>{esc(_('about_lang_body'))}</p>

  <h2>{esc(_('about_feeds'))}</h2>
  <p>{_('about_feeds_body',
         feed='<a href="feed.xml">feed.xml</a>',
         data=f'<a href="{root}data.json">data.json</a>')}</p>

  <p>{esc(_('about_caveat'))}</p>
</section>"""
    return layout(f"{SITE_TITLE} — {_('about_title')}", body,
                  description=_('about_caveat'), nav_active="about",
                  page_path="about.html")


def page_404() -> str:
    """GitHub Pages serves this for any unknown path.

    The only page besides the masthead where the mascot appears at size — a
    dead link is the one moment on this site where nothing is at stake.
    """
    root = "" if LANG == "en" else "../"
    body = f"""
<section class="notfound">
  <img src="{root}assets/mormotsaurus.png" alt="" width="96" height="96" decoding="async">
  <h1>{esc(_('notfound_title'))}</h1>
  <p>{esc(_('notfound_body'))}</p>
  <p class="notfound-links"><a href="index.html">{esc(_('nav_today'))}</a> ·
     <a href="archive.html">{esc(_('nav_archive'))}</a> ·
     <a href="units.html">{esc(_('nav_units'))}</a></p>
</section>"""
    return layout(f"{SITE_TITLE} — {_('notfound_page')}", body,
                  description=_('notfound_body'), nav_active="",
                  page_path="404.html")


def build_feed(editions: list[Edition], base_url: str) -> str:
    items = []
    for edition in editions[:30]:
        link = f"{base_url}/edition/{edition.date}.html" if base_url else f"edition/{edition.date}.html"
        pub = parse_iso(edition.date + "T07:00:00Z").strftime("%a, %d %b %Y %H:%M:%S +0000")
        bullets = "".join(f"<li>{esc(t)}</li>" for t in edition.tldr)
        body = (f"<p>{esc(edition.intro)}</p>"
                + (f"<ul>{bullets}</ul>" if bullets else ""))
        items.append(f"""  <item>
    <title>{esc(edition.date)} — {esc(edition.title)}</title>
    <link>{esc(link)}</link>
    <guid isPermaLink="false">mormot2-daily-{esc(edition.date)}</guid>
    <pubDate>{pub}</pubDate>
    <description>{esc(body)}</description>
  </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>{esc(SITE_TITLE)}</title>
  <link>{esc(base_url or 'https://github.com/' + UPSTREAM)}</link>
  <description>{esc(SITE_TAGLINE)}</description>
  <language>en</language>
  <lastBuildDate>{parse_iso(iso(utcnow())).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>
{chr(10).join(items)}
</channel></rss>
"""


def build_data(editions: list[Edition]) -> str:
    payload = {
        "site": SITE_TITLE,
        "upstream": UPSTREAM,
        "generated_at": iso(utcnow()),
        "editions": [{
            "date": e.date,
            "title": e.title,
            "intro": e.intro,
            "tldr": e.tldr,
            "risk_level": e.risk,
            "reviewed": e.reviewed,
            "version": e.version,
            "totals": e.totals,
            "entries": [{
                "sha": x.sha, "headline": x.headline, "category": x.category,
                "severity": x.severity, "action": x.action, "units": x.units,
                "impact": x.impact, "what_changed": x.what_changed,
                "confidence": x.confidence, "reviewed": x.reviewed, "url": x.url,
            } for x in e.entries],
        } for e in editions],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def normalise_base_url(value: str) -> str:
    """Canonical public origin for the absolute links in feed.xml.

    GitHub Pages reports http:// until "Enforce HTTPS" finishes provisioning, and
    it reports whichever custom domain was set when the build ran — a feed full of
    http:// or of a retired hostname is dead links in someone's reader.
    """
    url = (value or "").strip().rstrip("/")
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if url and not url.startswith("https://"):
        url = "https://" + url
    return url


def build_language(editions: list[Edition], out: pathlib.Path,
                   base_url: str) -> None:
    """Write one complete language tree. Assets are shared and live at the root."""
    (out / "edition").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page_index(editions), encoding="utf-8")
    (out / "archive.html").write_text(page_archive(editions), encoding="utf-8")
    (out / "units.html").write_text(page_units(editions), encoding="utf-8")
    (out / "about.html").write_text(page_about(), encoding="utf-8")
    (out / "404.html").write_text(page_404(), encoding="utf-8")
    (out / "feed.xml").write_text(build_feed(editions, base_url), encoding="utf-8")
    for i, edition in enumerate(editions):
        prev = editions[i + 1] if i + 1 < len(editions) else None
        nxt = editions[i - 1] if i > 0 else None
        (out / "edition" / f"{edition.date}.html").write_text(
            page_edition(edition, prev, nxt, editions), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(SITE_OUT))
    parser.add_argument("--base-url", default="")
    parser.add_argument("--langs", default=",".join(LANGS),
                        help="comma-separated subset to build, e.g. en,fr")
    args = parser.parse_args()

    global BASE_URL, LANG
    base_url = BASE_URL = normalise_base_url(args.base_url)
    langs = [l.strip() for l in args.langs.split(",") if l.strip() in LANGS] or ["en"]

    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SITE_SRC / "assets", out / "assets")
    if MEDIA_SRC.is_dir():
        shutil.copytree(MEDIA_SRC, out / "medias")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    count = 0
    for lang in langs:
        LANG = lang
        editions = load_editions(lang)
        if not editions:
            print("no data yet — run scripts/fetch_commits.py first", file=sys.stderr)
            editions = [build_edition(utcnow().strftime("%Y-%m-%d"), {}, {}, lang)]
        count = len(editions)
        build_language(editions, out / prefix(lang).rstrip("/") if prefix(lang) else out,
                       base_url)
        if lang == "en":
            # One machine-readable payload for the whole site, carrying every
            # language, so a consumer does not have to fetch four files.
            (out / "data.json").write_text(build_data(editions), encoding="utf-8")

    print(f"Built {count} edition(s) x {len(langs)} language(s) "
          f"({', '.join(langs)}) into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
