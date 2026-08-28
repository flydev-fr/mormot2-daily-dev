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
    ANALYSIS_DIR, RAW_DIR, SITE_OUT, SITE_SRC, SITE_TAGLINE, SITE_TITLE, UPSTREAM,
    iso, parse_iso, read_json, short, utcnow,
)
from heuristics import classify

# --------------------------------------------------------------------------- taxonomy

SECTIONS = [
    ("breaking", "Breaking changes", "Application code may need to change."),
    ("security", "Security", "Anything with a security angle."),
    ("fix", "Fixes", "Bugs squashed upstream."),
    ("feature", "New features", "New capabilities you can start using."),
    ("performance", "Performance", "Same behaviour, less time or memory."),
    ("compat", "Compiler & platform", "Delphi / FPC / OS compatibility."),
    ("deprecation", "Deprecations", "Still there, on the way out."),
    ("refactor", "Under the hood", "Internal reshaping, no API promise broken."),
    ("tests", "Tests", "Coverage and regression work."),
    ("docs", "Docs", "Documentation and comments."),
    ("chore", "Housekeeping", "Merges, bookkeeping, small chores."),
]
SECTION_ORDER = {key: i for i, (key, _, _) in enumerate(SECTIONS)}
SECTION_TITLE = {key: title for key, title, _ in SECTIONS}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
ACTION_LABEL = {
    "none": "No action",
    "review": "Worth a look",
    "upgrade-recommended": "Upgrade recommended",
    "migration-required": "Migration required",
}
RISK_LABEL = {
    "calm": ("Calm day", "Nothing here demands your attention today."),
    "worth-a-look": ("Worth a look", "Something in here is likely relevant to you."),
    "act-now": ("Act now", "There is a change here that can bite a running system."),
}


# Rounded square in the accent blue, as a data: URI — no extra request, no 404.
FAVICON = ("%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='8' fill='%232a78d6'/%3E"
           "%3Cpath d='M8 22V10h3l5 7 5-7h3v12h-3v-7l-5 7-5-7v7z' fill='white'/%3E"
           "%3C/svg%3E")


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

    @property
    def pretty_date(self) -> str:
        return parse_iso(self.date + "T00:00:00Z").strftime("%A %d %B %Y")

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

    def sections(self) -> list[tuple[str, str, str, list[Entry]]]:
        out = []
        for key, title, blurb in SECTIONS:
            bucket = sorted([e for e in self.entries if e.category == key],
                            key=lambda e: e.sort_key)
            if bucket:
                out.append((key, title, blurb, bucket))
        return out


def load_editions() -> list[Edition]:
    dates = sorted({p.stem for p in RAW_DIR.glob("*.json")} |
                   {p.stem for p in ANALYSIS_DIR.glob("*.json")}, reverse=True)
    editions = []
    for date in dates:
        raw = read_json(RAW_DIR / f"{date}.json", {}) or {}
        analysis = read_json(ANALYSIS_DIR / f"{date}.json", {}) or {}
        editions.append(build_edition(date, raw, analysis))
    return editions


def build_edition(date: str, raw: dict, analysis: dict) -> Edition:
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
        entries.append(_entry(item, commit, reviewed=True))

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
        }, commit, reviewed=False))

    entries.sort(key=lambda e: e.sort_key)
    count = len(commits)
    fallback_title = ("A quiet day upstream" if count == 0
                      else f"{count} commit{'s' if count != 1 else ''} landed upstream")
    fallback_intro = (
        "No commits were pushed to the upstream repository in this window. "
        "Nothing to read today — enjoy the coffee."
        if count == 0 else
        "This edition has not been reviewed yet: the entries below are classified "
        "automatically from commit messages and diffs, without an editorial pass. "
        "Treat the categories as hints and follow the commit links for the truth.")

    return Edition(
        date=date,
        title=analysis.get("edition_title") or fallback_title,
        intro=analysis.get("intro") or fallback_intro,
        tldr=analysis.get("tldr") or [],
        risk=analysis.get("risk_level") or ("calm" if count == 0 else ""),
        upgrade_advice=analysis.get("upgrade_advice") or "",
        notes=analysis.get("notes") or "",
        themes=analysis.get("themes") or [],
        entries=entries,
        reviewed=reviewed,
        version=raw.get("version") or {},
        totals=raw.get("totals") or {"commits": count, "additions": 0, "deletions": 0},
        generated_at=raw.get("generated_at") or "",
    )


def _entry(item: dict, commit: dict, reviewed: bool) -> Entry:
    stats = commit.get("stats", {}) or {}
    units = item.get("units") or commit.get("units") or []
    return Entry(
        sha=commit.get("sha") or item.get("sha", ""),
        headline=item.get("headline") or commit.get("subject", ""),
        category=item.get("category", "chore"),
        severity=item.get("severity", "low"),
        what_changed=item.get("what_changed", ""),
        impact=item.get("impact", ""),
        action=item.get("action", "none"),
        action_detail=item.get("action_detail", ""),
        units=units,
        api_changes=item.get("api_changes") or [],
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
    label = SEVERITY_LABEL.get(severity, severity.title())
    return (f'<span class="sev sev-{esc(severity)}" title="Severity: {esc(label)}">'
            f'<span class="dot" aria-hidden="true"></span>{esc(label)}</span>')


def action_badge(entry: Entry) -> str:
    if entry.action == "none":
        return ""
    detail = f'<p class="action-detail">{esc(entry.action_detail)}</p>' if entry.action_detail else ""
    return (f'<div class="action action-{esc(entry.action)}">'
            f'<span class="action-label">{esc(ACTION_LABEL.get(entry.action, entry.action))}</span>'
            f'{detail}</div>')


def entry_card(entry: Entry) -> str:
    meta = []
    if entry.author:
        meta.append(esc(entry.author))
    if entry.date:
        meta.append(parse_iso(entry.date).strftime("%H:%M UTC"))
    if entry.additions or entry.deletions:
        meta.append(f'<span class="diffstat">'
                    f'<span class="add">+{entry.additions}</span>'
                    f'<span class="del">-{entry.deletions}</span></span>')
    if entry.pr:
        meta.append(f'<a href="https://github.com/{UPSTREAM}/pull/{entry.pr}">PR #{entry.pr}</a>')

    units = "".join(f'<a class="chip unit" href="units.html#{esc(u)}">{esc(u)}</a>'
                    for u in entry.units[:6])
    api = ""
    if entry.api_changes:
        rows = "".join(
            f'<li><code>{esc(c.get("symbol", ""))}</code>'
            f'<span class="api-kind api-{esc(c.get("change", ""))}">{esc(c.get("change", ""))}</span>'
            f'{" — " + esc(c.get("note")) if c.get("note") else ""}</li>'
            for c in entry.api_changes)
        api = f'<div class="api"><h4>Public API</h4><ul>{rows}</ul></div>'

    what = (f'<div class="block"><h4>What changed</h4><p>{esc(entry.what_changed)}</p></div>'
            if entry.what_changed else "")
    impact = (f'<div class="block impact"><h4>What it means for you</h4>'
              f'<p>{esc(entry.impact)}</p></div>' if entry.impact else "")
    unreviewed = ('<span class="chip warn" title="Classified automatically from the '
                  'commit message and diff — no editorial pass">auto-classified</span>'
                  if not entry.reviewed else "")
    interp = ('<span class="chip soft" title="This is the reviewer\'s reading of the '
              'consequences, not something the commit states">interpretation</span>'
              if entry.reviewed and entry.confidence == "interpretation" else "")

    subject_line = ""
    if entry.subject and entry.subject.strip().lower() != entry.headline.strip().lower():
        subject_line = f'<p class="subject"><code>{esc(entry.subject)}</code></p>'

    return f"""
<article class="entry" id="c-{esc(short(entry.sha))}"
         data-category="{esc(entry.category)}" data-severity="{esc(entry.severity)}"
         data-search="{esc((entry.headline + ' ' + entry.subject + ' ' + ' '.join(entry.units) + ' ' + entry.impact).lower())}">
  <header>
    <div class="entry-tags">{severity_chip(entry.severity)}
      {chip(SECTION_TITLE.get(entry.category, entry.category), 'cat cat-' + entry.category)}
      {unreviewed}{interp}</div>
    <h3>{esc(entry.headline)}</h3>
    {subject_line}
  </header>
  {what}{impact}{action_badge(entry)}{api}
  <footer>
    <div class="units">{units}</div>
    <div class="meta">{" · ".join(meta)}
      <a class="sha" href="{esc(entry.url)}"><code>{esc(short(entry.sha))}</code></a></div>
  </footer>
</article>"""


def activity_chart(editions: list[Edition], days: int = 30) -> str:
    """Commits per day — one series, one hue, direct labels on the extremes."""
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
        href = f'edition/{key}.html' if exists else ""
        label = f"{key}: {value} commit{'s' if value != 1 else ''}"
        rect = (f'<rect class="{cls}" x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" '
                f'height="{max(h, 0.8):.2f}" rx="0.6"><title>{esc(label)}</title></rect>')
        bars.append(f'<a href="{href}">{rect}</a>' if href else rect)

    first, last = series[0][0], series[-1][0]
    return f"""
<figure class="chart">
  <figcaption>
    <span class="chart-title">Upstream activity</span>
    <span class="chart-note">commits per day · last {days} days · peak {peak}</span>
  </figcaption>
  <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img"
       aria-label="Commits per day over the last {days} days, peak {peak}">
    {"".join(bars)}
  </svg>
  <div class="chart-axis"><span>{esc(first)}</span><span>{esc(last)}</span></div>
</figure>"""


def category_chart(edition: Edition) -> str:
    """Category distribution — magnitude, so one hue with direct labels."""
    counts = edition.counts
    rows = []
    peak = max(counts.values(), default=1) or 1
    for key, title, _ in SECTIONS:
        value = counts.get(key, 0)
        if not value:
            continue
        rows.append(
            f'<div class="cat-row"><span class="cat-name">{esc(title)}</span>'
            f'<span class="cat-track"><span class="cat-bar" '
            f'style="width:{value / peak * 100:.1f}%"></span></span>'
            f'<span class="cat-value">{value}</span></div>')
    if not rows:
        return ""
    return f'<div class="cat-chart"><h3>What this edition is made of</h3>{"".join(rows)}</div>'


# ----------------------------------------------------------------------------- pages

def layout(title: str, body: str, *, description: str, base: str = "",
           extra_head: str = "", nav_active: str = "") -> str:
    def nav(href: str, label: str, key: str) -> str:
        active = ' class="active"' if key == nav_active else ""
        return f'<a href="{base}{href}"{active}>{label}</a>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,{FAVICON}">
<link rel="alternate" type="application/rss+xml" title="{esc(SITE_TITLE)}" href="{base}feed.xml">
<link rel="stylesheet" href="{base}assets/style.css">
{extra_head}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site">
  <div class="wrap">
    <a class="brand" href="{base}index.html">
      <span class="brand-mark" aria-hidden="true"></span>
      <span><strong>{esc(SITE_TITLE)}</strong><em>{esc(SITE_TAGLINE)}</em></span>
    </a>
    <nav>
      {nav('index.html', 'Today', 'today')}
      {nav('archive.html', 'Archive', 'archive')}
      {nav('units.html', 'Units', 'units')}
      {nav('about.html', 'About', 'about')}
      <a href="https://github.com/{UPSTREAM}" rel="noopener">Upstream</a>
      <button id="theme" type="button" aria-label="Switch colour theme">
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
    <p>Generated from public commits of
       <a href="https://github.com/{UPSTREAM}">{UPSTREAM}</a>.
       Summaries are written by an AI reviewer and can be wrong — the commit links are
       the source of truth. Not affiliated with Synopse.</p>
    <p class="stamp">Built {esc(iso(utcnow()))} ·
       <a href="{base}feed.xml">RSS</a> · <a href="{base}data.json">JSON</a></p>
  </div>
</footer>
<script src="{base}assets/app.js"></script>
</body>
</html>
"""


def edition_header(edition: Edition, base: str, *, permalink: bool) -> str:
    risk = RISK_LABEL.get(edition.risk)
    risk_html = ""
    if risk:
        risk_html = (f'<div class="risk risk-{esc(edition.risk)}">'
                     f'<strong>{esc(risk[0])}</strong><span>{esc(risk[1])}</span></div>')
    version = edition.version or {}
    facts = []
    if version.get("after"):
        before = version.get("before")
        facts.append(f'<div class="fact"><span class="k">Build</span>'
                     f'<span class="v">{esc(before + " → " if before else "")}'
                     f'{esc(version["after"])}</span></div>')
    facts.append(f'<div class="fact"><span class="k">Commits</span>'
                 f'<span class="v">{edition.totals.get("commits", 0)}</span></div>')
    facts.append(f'<div class="fact"><span class="k">Lines</span>'
                 f'<span class="v"><span class="add">+{edition.totals.get("additions", 0)}</span> '
                 f'<span class="del">-{edition.totals.get("deletions", 0)}</span></span></div>')
    facts.append(f'<div class="fact"><span class="k">Read</span>'
                 f'<span class="v">{edition.read_minutes} min</span></div>')

    title = esc(edition.title)
    if permalink:
        title = f'<a href="{base}edition/{edition.date}.html">{title}</a>'
    tldr = ""
    if edition.tldr:
        items = "".join(f"<li>{esc(item)}</li>" for item in edition.tldr)
        tldr = f'<div class="tldr"><h2>The short version</h2><ul>{items}</ul></div>'
    banner = ("" if edition.reviewed else
              '<p class="banner">Not reviewed yet — entries below are auto-classified '
              'from commit messages and diffs.</p>')

    return f"""
<section class="edition-head">
  <p class="kicker"><time datetime="{esc(edition.date)}">{esc(edition.pretty_date)}</time></p>
  <h1>{title}</h1>
  {banner}
  <p class="intro">{esc(edition.intro)}</p>
  {risk_html}
  <div class="facts">{"".join(facts)}</div>
  {tldr}
</section>"""


def themes_block(edition: Edition) -> str:
    if not edition.themes:
        return ""
    blocks = []
    for theme in edition.themes:
        links = " ".join(
            f'<a href="#c-{esc(short(s))}"><code>{esc(short(s))}</code></a>'
            for s in theme.get("shas", []))
        blocks.append(f'<div class="theme"><h3>{esc(theme.get("title", ""))}</h3>'
                      f'<p>{esc(theme.get("summary", ""))}</p>'
                      f'<p class="theme-links">{links}</p></div>')
    return f'<section class="themes"><h2>The thread of the day</h2>{"".join(blocks)}</section>'


def filters_bar(edition: Edition) -> str:
    counts = edition.counts
    buttons = ['<button class="f active" data-filter="all">'
               f'All <span>{len(edition.entries)}</span></button>']
    for key, title, _ in SECTIONS:
        if counts.get(key):
            buttons.append(f'<button class="f" data-filter="{esc(key)}">'
                           f'{esc(title)} <span>{counts[key]}</span></button>')
    return f"""
<div class="toolbar">
  <div class="filters">{"".join(buttons)}</div>
  <label class="search"><span class="sr">Search this edition</span>
    <input type="search" id="q" placeholder="Search units, symbols, impact…"></label>
</div>"""


def edition_body(edition: Edition, base: str) -> str:
    if not edition.entries:
        return ('<section class="empty"><h2>Nothing shipped</h2>'
                '<p>No commits landed upstream in this window.</p></section>')
    parts = [themes_block(edition), category_chart(edition), filters_bar(edition)]
    for key, title, blurb, bucket in edition.sections():
        cards = "".join(entry_card(e) for e in bucket)
        parts.append(f"""
<section class="section" data-section="{esc(key)}">
  <div class="section-head"><h2>{esc(title)}</h2><p>{esc(blurb)}</p>
    <span class="count">{len(bucket)}</span></div>
  {cards}
</section>""")
    if edition.upgrade_advice:
        parts.append(f'<section class="advice"><h2>Should you pull this?</h2>'
                     f'<p>{esc(edition.upgrade_advice)}</p></section>')
    if edition.notes:
        parts.append(f'<section class="notes"><h2>Reviewer notes</h2>'
                     f'<p>{esc(edition.notes)}</p></section>')
    return "".join(parts)


def page_index(editions: list[Edition]) -> str:
    latest = editions[0]
    older = editions[1:13]
    archive = "".join(
        f'<li><a href="edition/{e.date}.html"><time>{esc(e.date)}</time>'
        f'<span class="t">{esc(e.title)}</span>'
        f'<span class="n">{e.totals.get("commits", 0)}</span></a></li>' for e in older)
    more = ('<p class="more"><a href="archive.html">All editions →</a></p>'
            if len(editions) > 13 else "")
    body = f"""
{edition_header(latest, "", permalink=True)}
{activity_chart(editions)}
{edition_body(latest, "")}
<section class="archive-preview">
  <h2>Earlier editions</h2>
  <ul class="archive-list">{archive}</ul>
  {more}
</section>"""
    return layout(f"{SITE_TITLE} — {latest.title}", body,
                  description=latest.intro[:180], nav_active="today")


def page_edition(edition: Edition, prev: Edition | None, nxt: Edition | None) -> str:
    nav = []
    if nxt:
        nav.append(f'<a class="prevnext" href="{nxt.date}.html">← {esc(nxt.date)}</a>')
    if prev:
        nav.append(f'<a class="prevnext right" href="{prev.date}.html">{esc(prev.date)} →</a>')
    body = (edition_header(edition, "../", permalink=False)
            + edition_body(edition, "../")
            + f'<nav class="pager">{"".join(nav)}</nav>')
    return layout(f"{SITE_TITLE} — {edition.date}", body,
                  description=edition.intro[:180], base="../", nav_active="")


def page_archive(editions: list[Edition]) -> str:
    rows = []
    for edition in editions:
        badges = "".join(chip(SECTION_TITLE[k], "cat cat-" + k)
                         for k in ("breaking", "security", "feature")
                         if edition.counts.get(k))
        rows.append(
            f'<tr><td><a href="edition/{edition.date}.html">{esc(edition.date)}</a></td>'
            f'<td class="title">{esc(edition.title)} {badges}</td>'
            f'<td class="num">{edition.totals.get("commits", 0)}</td>'
            f'<td>{severity_chip(edition.top_severity)}</td></tr>')
    body = f"""
<section class="page-head"><h1>Archive</h1>
  <p>Every edition since the monitor started. {len(editions)} in total.</p></section>
{activity_chart(editions, 60)}
<table class="archive-table">
  <thead><tr><th>Date</th><th>Edition</th><th class="num">Commits</th><th>Top severity</th></tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>"""
    return layout(f"{SITE_TITLE} — Archive", body,
                  description="All mORMot2 Daily editions.", nav_active="archive")


def page_units(editions: list[Edition]) -> str:
    index: dict[str, list[tuple[str, Entry]]] = {}
    for edition in editions:
        for entry in edition.entries:
            for unit in entry.units:
                index.setdefault(unit, []).append((edition.date, entry))
    if not index:
        body = ('<section class="page-head"><h1>Units</h1>'
                '<p>No unit-level data yet.</p></section>')
        return layout(f"{SITE_TITLE} — Units", body,
                      description="Changes by mORMot2 unit.", nav_active="units")

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
<section class="page-head"><h1>Units</h1>
  <p>Which mORMot2 units have moved, and where to read about it.
     {len(index)} units tracked.</p></section>
{"".join(blocks)}"""
    return layout(f"{SITE_TITLE} — Units", body,
                  description="Changes by mORMot2 unit.", nav_active="units")


def page_about() -> str:
    body = f"""
<section class="page-head"><h1>About</h1></section>
<section class="prose">
  <p><strong>{esc(SITE_TITLE)}</strong> is a daily read of what changed in
     <a href="https://github.com/{UPSTREAM}">{UPSTREAM}</a> — the Synopse mORMot2
     framework for Delphi and FPC. Upstream commits are terse and written for the
     people who wrote them. This site rewrites them for everyone else: what changed,
     what it means for a backend already in production, and whether you need to do
     anything about it.</p>

  <h2>How an edition is made</h2>
  <ol>
    <li>A scheduled job pulls every new upstream commit with its diff.</li>
    <li>A first pass classifies each commit deterministically from its message and
        the files it touches.</li>
    <li><a href="https://jules.google">Jules</a> reads the diffs — and the surrounding
        source when the diff is not enough — and writes one structured JSON file per
        edition, following a fixed schema.</li>
    <li>That JSON is validated against the schema (SHAs must resolve to real commits,
        every non-merge commit must be covered) before it is merged. Anything that
        fails goes back to the reviewer with the errors.</li>
    <li>This site is generated from the validated JSON. The reviewer never writes
        HTML, so a bad review can be wrong — it cannot break the page.</li>
  </ol>

  <h2>How to read it</h2>
  <p>Entries carry a severity, a category and an action. <em>Interpretation</em>
     marks a claim that is the reviewer's reading rather than something the commit
     states. <em>Auto-classified</em> marks an entry that never got an editorial pass.
     Both are shown on purpose: you should know which sentences to trust.</p>

  <h2>Caveats</h2>
  <p>Summaries are machine-written and can be wrong or incomplete. The commit links
     are the source of truth. This site is an independent read of a public
     repository; it is not affiliated with Synopse or with the mORMot project.</p>

  <p>Feeds: <a href="feed.xml">RSS</a> · <a href="data.json">JSON</a></p>
</section>"""
    return layout(f"{SITE_TITLE} — About", body,
                  description="How this daily mORMot2 digest is produced.",
                  nav_active="about")


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(SITE_OUT))
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()

    editions = load_editions()
    if not editions:
        print("no data yet — run scripts/fetch_commits.py first", file=sys.stderr)
        editions = [build_edition(utcnow().strftime("%Y-%m-%d"), {}, {})]

    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "edition").mkdir(parents=True, exist_ok=True)
    shutil.copytree(SITE_SRC / "assets", out / "assets")

    (out / "index.html").write_text(page_index(editions), encoding="utf-8")
    (out / "archive.html").write_text(page_archive(editions), encoding="utf-8")
    (out / "units.html").write_text(page_units(editions), encoding="utf-8")
    (out / "about.html").write_text(page_about(), encoding="utf-8")
    (out / "feed.xml").write_text(build_feed(editions, args.base_url.rstrip("/")),
                                  encoding="utf-8")
    (out / "data.json").write_text(build_data(editions), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    for i, edition in enumerate(editions):
        prev = editions[i + 1] if i + 1 < len(editions) else None
        nxt = editions[i - 1] if i > 0 else None
        (out / "edition" / f"{edition.date}.html").write_text(
            page_edition(edition, prev, nxt), encoding="utf-8")

    print(f"Built {len(editions)} edition(s) into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
