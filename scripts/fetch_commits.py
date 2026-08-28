#!/usr/bin/env python3
"""Fetch new upstream mORMot2 commits (metadata + diffs) into data/raw/<date>.json.

Incremental: `data/state.json` remembers the last processed commit date and the
SHAs already published, so a re-run never duplicates work.

Environment:
  GITHUB_TOKEN   optional but strongly recommended (rate limits, 60/h anonymous)
  UPSTREAM_REPO  default "synopse/mORMot2"
  SINCE_DAYS     lookback when there is no state yet (default 1)
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

from common import (
    ANALYSIS_SCHEMA, NOISE_FILES, RAW_DIR, RAW_SCHEMA, ROOT, UPSTREAM,
    iso, load_state, save_state, short, utcnow, write_json,
)
from heuristics import annotate

API = "https://api.github.com"
MAX_PATCH_CHARS = int(os.environ.get("MAX_PATCH_CHARS", "12000"))
MAX_FILE_PATCH_CHARS = int(os.environ.get("MAX_FILE_PATCH_CHARS", "4000"))


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


def list_commits(since_iso: str, max_commits: int) -> list[dict]:
    out, page = [], 1
    while len(out) < max_commits:
        batch = api_get(f"/repos/{UPSTREAM}/commits",
                        {"since": since_iso, "per_page": 100, "page": page})
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out[:max_commits]


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="edition date (default: today, UTC)")
    parser.add_argument("--since", help="ISO timestamp overriding the stored state")
    parser.add_argument("--since-days", type=int,
                        default=int(os.environ.get("SINCE_DAYS", "1")))
    parser.add_argument("--max-commits", type=int,
                        default=int(os.environ.get("MAX_COMMITS", "60")))
    parser.add_argument("--force", action="store_true",
                        help="ignore seen_shas de-duplication")
    args = parser.parse_args()

    state = load_state()
    now = utcnow()
    edition = args.date or now.strftime("%Y-%m-%d")

    if args.since:
        since = args.since
    elif state.get("last_commit_date"):
        since = state["last_commit_date"]
    else:
        since = iso(now - datetime.timedelta(days=args.since_days))

    print(f"Fetching {UPSTREAM} commits since {since}", flush=True)
    listed = list_commits(since, args.max_commits)
    seen = set() if args.force else set(state.get("seen_shas", []))
    todo = [c["sha"] for c in listed if c["sha"] not in seen]
    print(f"  {len(listed)} listed, {len(todo)} new", flush=True)

    commits = []
    for sha in todo:
        record = build_record(sha)
        if record:
            commits.append(record)
            print(f"  + {record['short_sha']} {record['subject'][:78]}", flush=True)

    commits.sort(key=lambda c: c.get("date") or "", reverse=True)
    payload = {
        "schema": RAW_SCHEMA,
        "analysis_schema": ANALYSIS_SCHEMA,
        "edition": edition,
        "repo": UPSTREAM,
        "generated_at": iso(now),
        "range": {
            "since": since,
            "until": iso(now),
            "head_sha": commits[0]["sha"] if commits else None,
        },
        "version": upstream_version(commits),
        "totals": {
            "commits": len(commits),
            "additions": sum(c["stats"]["additions"] for c in commits),
            "deletions": sum(c["stats"]["deletions"] for c in commits),
        },
        "commits": commits,
    }

    # Several runs a day are normal (a manual re-run, a retry). Always merge with
    # what is already on disk for this edition — never overwrite it with a shorter
    # window, even when this run found nothing new.
    out = RAW_DIR / f"{edition}.json"
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    if previous:
        known = {c["sha"] for c in payload["commits"]}
        merged = payload["commits"] + [c for c in previous.get("commits", [])
                                       if c["sha"] not in known]
        merged.sort(key=lambda c: c.get("date") or "", reverse=True)
        payload["commits"] = merged
        payload["totals"] = {
            "commits": len(merged),
            "additions": sum(c["stats"]["additions"] for c in merged),
            "deletions": sum(c["stats"]["deletions"] for c in merged),
        }
        old_version = previous.get("version") or {}
        payload["version"]["before"] = old_version.get("before") or payload["version"]["before"]
        payload["version"]["after"] = payload["version"]["after"] or old_version.get("after")
        old_range = previous.get("range") or {}
        payload["range"]["since"] = min(filter(None, [since, old_range.get("since")]),
                                        default=since)
        payload["range"]["head_sha"] = (merged[0]["sha"] if merged
                                        else old_range.get("head_sha"))
    write_json(out, payload)
    print(f"Wrote {out.relative_to(ROOT)} ({payload['totals']['commits']} commits)")

    if commits:
        state["last_commit_date"] = commits[0]["date"]
        state["seen_shas"] = list(state.get("seen_shas", [])) + [c["sha"] for c in commits]
    state["last_run"] = iso(now)
    save_state(state)

    # Outputs consumed by the workflow.
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"edition={edition}\n")
            fh.write(f"new_commits={len(commits)}\n")
            fh.write(f"raw_path=data/raw/{edition}.json\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
