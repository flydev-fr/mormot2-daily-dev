#!/usr/bin/env python3
"""Dev helper: build a raw payload from a local clone instead of the GitHub API.

Useful offline, in a sandbox without GitHub API access, or to backfill an old
edition. Produces exactly the same shape as scripts/fetch_commits.py.

    git clone --depth 60 https://github.com/synopse/mORMot2 /tmp/mormot2
    python scripts/make_fixture.py --clone /tmp/mormot2 --date 2026-08-28
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from common import (
    ANALYSIS_SCHEMA, NOISE_FILES, RAW_DIR, RAW_SCHEMA, ROOT, UPSTREAM,
    iso, short, utcnow, write_json,
)
from fetch_commits import MAX_FILE_PATCH_CHARS, MAX_PATCH_CHARS, truncate, upstream_version
from heuristics import annotate

SEP = "\x1e"


def git(clone: str, *args: str) -> str:
    return subprocess.run(["git", "-C", clone, *args],
                          capture_output=True, text=True, check=True).stdout


def commit_shas(clone: str, date: str) -> list[str]:
    out = git(clone, "log", "--no-merges" if False else "--all-match",
              f"--since={date} 00:00:00 +0000", f"--until={date} 23:59:59 +0000",
              "--pretty=format:%H")
    return [line.strip() for line in out.splitlines() if line.strip()]


def build_record(clone: str, sha: str) -> dict:
    meta = git(clone, "show", "-s", f"--format=%H{SEP}%an{SEP}%aI{SEP}%P{SEP}%s{SEP}%b", sha)
    parts = meta.split(SEP)
    _, author, date, parents, subject = parts[:5]
    body = parts[5] if len(parts) > 5 else ""

    files, budget = [], MAX_PATCH_CHARS
    numstat = git(clone, "show", "--numstat", "--format=", sha)
    for line in numstat.splitlines():
        cells = line.split("\t")
        if len(cells) != 3:
            continue
        adds, dels, path = cells
        patch = ""
        if budget > 0 or path in NOISE_FILES:
            raw = git(clone, "show", "--format=", "--unified=3", sha, "--", path)
            patch, _ = truncate(raw, min(MAX_FILE_PATCH_CHARS, max(budget, 400)))
            if path not in NOISE_FILES:
                budget -= len(patch)
        files.append({
            "path": path,
            "status": "modified",
            "additions": int(adds) if adds.isdigit() else 0,
            "deletions": int(dels) if dels.isdigit() else 0,
            "patch": patch,
            "patch_truncated": False,
        })

    record = {
        "sha": sha,
        "short_sha": short(sha),
        "subject": subject.strip(),
        "body": body.strip(),
        "author": author,
        "date": date,
        "url": f"https://github.com/{UPSTREAM}/commit/{sha}",
        "parents": parents.split(),
        "stats": {
            "additions": sum(f["additions"] for f in files),
            "deletions": sum(f["deletions"] for f in files),
            "files": len([f for f in files if f["path"] not in NOISE_FILES]),
        },
        "files": files,
    }
    return annotate(record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clone", required=True, help="path to a local mORMot2 clone")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD (UTC author date)")
    args = parser.parse_args()

    shas = commit_shas(args.clone, args.date)
    if not shas:
        print(f"no commits on {args.date} in {args.clone}", file=sys.stderr)
    commits = [build_record(args.clone, sha) for sha in shas]
    commits.sort(key=lambda c: c["date"], reverse=True)

    payload = {
        "schema": RAW_SCHEMA,
        "analysis_schema": ANALYSIS_SCHEMA,
        "edition": args.date,
        "repo": UPSTREAM,
        "generated_at": iso(utcnow()),
        "range": {
            "since": f"{args.date}T00:00:00Z",
            "until": f"{args.date}T23:59:59Z",
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
    out = RAW_DIR / f"{args.date}.json"
    write_json(out, payload)
    print(f"Wrote {out.relative_to(ROOT)} ({len(commits)} commits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
