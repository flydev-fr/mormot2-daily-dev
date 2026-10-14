#!/usr/bin/env python3
"""Fetch one complete mORMot2 calendar day into data/raw/<date>.json.

By default the edition is yesterday in ``Europe/Zagreb``.  Waiting until the
next morning closes the whole calendar day before publishing it.  Commits are
selected from the Git graph between the heads immediately before and after the
day, rather than from a rolling author-date cursor.  This also catches older
topic-branch commits which only became reachable when a pull request was merged.

Environment:
  GITHUB_TOKEN   optional but strongly recommended (rate limits, 60/h anonymous)
  UPSTREAM_REPO  default "synopse/mORMot2"
  EDITION_TIMEZONE  calendar timezone (default "Europe/Zagreb")
  MAX_COMMITS    safety cap per run (default 60)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import (
    ANALYSIS_SCHEMA, NOISE_FILES, RAW_DIR, RAW_SCHEMA, ROOT, UPSTREAM,
    iso, load_state, parse_iso, save_state, short, utcnow, write_json,
)
from heuristics import annotate

API = "https://api.github.com"
MAX_PATCH_CHARS = int(os.environ.get("MAX_PATCH_CHARS", "12000"))
MAX_FILE_PATCH_CHARS = int(os.environ.get("MAX_FILE_PATCH_CHARS", "4000"))
EDITION_TIMEZONE = os.environ.get("EDITION_TIMEZONE", "Europe/Zagreb")


def api_get(path: str, params: dict | None = None, retries: int = 4):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mormot2-monitor",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and attempt < retries - 1:
                wait = min(60, 5 * 2 ** attempt)
                print(f"  rate limited ({exc.code}), retrying in {wait}s", flush=True)
                time.sleep(wait)
                continue
            print(f"  HTTP {exc.code} for {url}", file=sys.stderr)
            raise
        except urllib.error.URLError as exc:
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            print(f"  network error for {url}: {exc}", file=sys.stderr)
            raise
    return None


def calendar_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown edition timezone: {name}") from exc


def default_edition(now: datetime.datetime, timezone_name: str) -> str:
    """Return the last fully closed local calendar day."""
    local_today = now.astimezone(calendar_timezone(timezone_name)).date()
    return (local_today - datetime.timedelta(days=1)).isoformat()


def edition_bounds(edition: str, timezone_name: str) -> tuple[str, str]:
    """Return the local day's half-open [start, end) bounds as UTC ISO strings."""
    try:
        day = datetime.date.fromisoformat(edition)
    except ValueError as exc:
        raise ValueError(f"invalid edition date: {edition}") from exc
    timezone = calendar_timezone(timezone_name)
    start = datetime.datetime.combine(day, datetime.time.min, timezone)
    end = datetime.datetime.combine(day + datetime.timedelta(days=1),
                                    datetime.time.min, timezone)
    return iso(start), iso(end)


def head_at_or_before(until_iso: str) -> str | None:
    """Return the default-branch head at a UTC boundary."""
    listed = api_get(f"/repos/{UPSTREAM}/commits",
                     {"until": until_iso, "per_page": 1, "page": 1}) or []
    return listed[0]["sha"] if listed else None


def compare_commit_shas(base: str | None, head: str | None,
                        max_commits: int) -> list[str]:
    """Return every commit which became reachable between two branch heads."""
    if not head or base == head:
        return []
    if not base:
        raise RuntimeError("cannot compare the edition: no commit before its start")

    path = f"/repos/{UPSTREAM}/compare/{base}...{head}"
    first = api_get(path, {"per_page": 100, "page": 1}) or {}
    status = first.get("status")
    if status not in ("ahead", "identical"):
        raise RuntimeError(f"unexpected Git comparison status: {status or 'missing'}")

    total = int(first.get("ahead_by", first.get("total_commits", 0)) or 0)
    if total > max_commits:
        raise RuntimeError(
            f"edition contains {total} commits, above MAX_COMMITS={max_commits}; "
            "raise the cap instead of publishing a truncated edition")

    commits = list(first.get("commits", []))
    page = 2
    while len(commits) < total:
        payload = api_get(path, {"per_page": 100, "page": page}) or {}
        batch = payload.get("commits", [])
        if not batch:
            break
        commits.extend(batch)
        page += 1
    if len(commits) != total:
        raise RuntimeError(f"Git comparison returned {len(commits)} of {total} commits")
    return [commit["sha"] for commit in commits]


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if text is None:
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]", True


def build_record(sha: str) -> dict | None:
    detail = api_get(f"/repos/{UPSTREAM}/commits/{sha}")
    if not detail:
        return None

    message = (detail["commit"]["message"] or "").strip()
    subject, _, body = message.partition("\n")

    files, budget = [], MAX_PATCH_CHARS
    for f in detail.get("files", []):
        path = f.get("filename", "")
        patch, cut = truncate(f.get("patch", ""), min(MAX_FILE_PATCH_CHARS, max(budget, 0)))
        budget -= len(patch)
        files.append({
            "path": path,
            "status": f.get("status"),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            # Version bookkeeping files keep their one-line patch: that is where the
            # upstream build number comes from. They are hidden from the site.
            "patch": patch,
            "patch_truncated": cut,
        })

    stats = detail.get("stats", {}) or {}
    author = detail.get("commit", {}).get("author", {}) or {}
    record = {
        "sha": sha,
        "short_sha": short(sha),
        "subject": subject.strip(),
        "body": body.strip(),
        "author": author.get("name") or "unknown",
        "date": author.get("date"),
        "url": detail.get("html_url"),
        "parents": [p["sha"] for p in detail.get("parents", [])],
        "stats": {
            "additions": stats.get("additions", 0),
            "deletions": stats.get("deletions", 0),
            "files": len([f for f in files if f["path"] not in NOISE_FILES]),
        },
        "files": files,
    }
    return annotate(record)


def upstream_version(commits: list[dict]) -> dict:
    """mORMot ships its build number in src/mormot.commit.inc ('2.4.16618')."""
    version = {"after": None, "before": None}
    for commit in commits:                       # newest first
        for f in commit.get("files", []):
            if f["path"] == "src/mormot.commit.inc":
                for line in (f.get("patch") or "").splitlines():
                    text = line[1:].strip().strip("'")
                    if line.startswith("+") and not line.startswith("+++") and text:
                        version["after"] = version["after"] or text
                    elif line.startswith("-") and not line.startswith("---") and text:
                        version["before"] = text
    return version


def payload_changed(previous: dict | None, current: dict) -> bool:
    """Ignore generation time when deciding whether the repository must change."""
    if previous is None:
        return bool(current.get("commits"))
    old = dict(previous)
    new = dict(current)
    old.pop("generated_at", None)
    new.pop("generated_at", None)
    return old != new


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",
                        help="edition date (default: yesterday in the edition timezone)")
    parser.add_argument("--timezone", default=EDITION_TIMEZONE,
                        help=f"calendar timezone (default: {EDITION_TIMEZONE})")
    parser.add_argument("--since",
                        help="override the edition's UTC start boundary")
    parser.add_argument("--max-commits", type=int,
                        default=int(os.environ.get("MAX_COMMITS", "60")))
    parser.add_argument("--force", action="store_true",
                        help="re-fetch details already cached in this edition")
    args = parser.parse_args()

    state = load_state()
    now = utcnow()
    edition = args.date or default_edition(now, args.timezone)
    since, until = edition_bounds(edition, args.timezone)
    if args.since:
        since = iso(parse_iso(args.since))

    # The boundary is exclusive. GitHub's `until` is inclusive and commit
    # timestamps have one-second precision, so ask for the previous second.
    before_start = iso(parse_iso(since) - datetime.timedelta(seconds=1))
    before_end = iso(parse_iso(until) - datetime.timedelta(seconds=1))
    base_sha = head_at_or_before(before_start)
    head_sha = head_at_or_before(before_end)
    listed_shas = compare_commit_shas(base_sha, head_sha, args.max_commits)

    out = RAW_DIR / f"{edition}.json"
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    cached = {} if args.force else {
        commit["sha"]: commit for commit in (previous or {}).get("commits", [])
    }
    todo = [sha for sha in listed_shas if sha not in cached]
    print(f"Fetching {UPSTREAM} calendar day {edition} ({since} to {until})", flush=True)
    print(f"  {len(listed_shas)} in Git graph, {len(todo)} details to fetch", flush=True)

    records = dict(cached)
    for sha in listed_shas:
        if sha in records:
            continue
        record = build_record(sha)
        if record:
            records[sha] = record
            print(f"  + {record['short_sha']} {record['subject'][:78]}", flush=True)

    missing = [sha for sha in listed_shas if sha not in records]
    if missing:
        raise RuntimeError(f"failed to fetch {len(missing)} commit detail record(s)")
    commits = [records[sha] for sha in listed_shas]

    commits.sort(key=lambda c: c.get("date") or "", reverse=True)
    payload = {
        "schema": RAW_SCHEMA,
        "analysis_schema": ANALYSIS_SCHEMA,
        "edition": edition,
        "repo": UPSTREAM,
        "generated_at": iso(now),
        "range": {
            "since": since,
            "until": until,
            "base_sha": base_sha,
            "head_sha": head_sha,
        },
        "version": upstream_version(commits),
        "totals": {
            "commits": len(commits),
            "additions": sum(c["stats"]["additions"] for c in commits),
            "deletions": sum(c["stats"]["deletions"] for c in commits),
        },
        "commits": commits,
    }

    changed = payload_changed(previous, payload)
    if changed:
        write_json(out, payload)
        print(f"Wrote {out.relative_to(ROOT)} ({payload['totals']['commits']} commits)")
    else:
        print(f"Unchanged {out.relative_to(ROOT)} ({payload['totals']['commits']} commits)")

    if commits:
        state["last_commit_date"] = commits[0]["date"]
        state["seen_shas"] = list(state.get("seen_shas", [])) + listed_shas
    state["last_run"] = iso(now)
    save_state(state)

    # Outputs consumed by the workflow.
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"edition={edition}\n")
            fh.write(f"new_commits={len(todo)}\n")
            fh.write(f"payload_changed={'true' if changed else 'false'}\n")
            fh.write(f"raw_path=data/raw/{edition}.json\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
