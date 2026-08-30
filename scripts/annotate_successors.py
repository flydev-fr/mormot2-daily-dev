#!/usr/bin/env python3
"""Add look-ahead to a raw payload: what landed after each commit, and fixed it.

An edition is a window closed at midnight, but the code settles over several days.
On 2026-08-28 the digest praised the lockless wake-up rewrite (16617, 16618) with
"no action needed"; five commits later, 16623 fixed an out of range on that very
path. The reviewer had no way to know — the information was not in its input.

This walks forward past the end of the edition and records, per commit, the later
commits that touch the same routines, flagging the ones whose subject reads like a
fix. The reviewer can then say "land on 16628, not 16618" instead of "today looks
fine".

    python scripts/annotate_successors.py --edition 2026-08-28 --clone /path/to/mORMot2
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys

from common import RAW_DIR, read_json, write_json

FIX = re.compile(r"\b(fix(ed|es|ing)?|regression|revert|broke|breaks|deadlock|"
                 r"out of range|leak|crash|workaround)\b", re.I)
NOISE = {"src/mormot.commit.inc", "src/mormot.commit-num.inc"}
ROUTINE = re.compile(r"^(function|procedure|constructor|destructor)\s+(\S+)", re.I)


def git(clone: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", clone, *args], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def changed_lines(clone: str, sha: str, path: str) -> list[int]:
    lines = []
    diff = git(clone, "show", "-U0", "--format=", sha, "--", path)
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        lines.extend(range(start, start + max(count, 1)))
    return lines


def touched_routines(clone: str, sha: str) -> tuple[set[str], set[str]]:
    """Files and routine names a commit touches.

    'Same file' is far too coarse here — mormot.core.base.pas is touched by nearly
    everything, so it would turn unrelated commits into successors. Git cannot give
    the enclosing routine either: it has no Pascal funcname regex, so a hunk header
    reads `@@ -3849 +3849 @@ begin`. So walk back from each changed line to the
    nearest routine header at column 0, the way the implementation section is written.
    """
    files, routines = set(), set()
    for line in git(clone, "show", "--numstat", "--format=", sha).splitlines():
        cells = line.split("\t")
        if len(cells) == 3 and cells[2] not in NOISE:
            files.add(cells[2])

    for path in files:
        if not path.endswith((".pas", ".inc", ".dpr")):
            continue
        text = git(clone, "show", f"{sha}:{path}")
        if not text:
            continue
        src = text.splitlines()
        heads = [(i, ROUTINE.match(l)) for i, l in enumerate(src) if ROUTINE.match(l)]
        if not heads:
            continue
        starts = [i for i, _ in heads]
        for n in changed_lines(clone, sha, path):
            idx = n - 1
            begin = None
            for i, s_ in enumerate(starts):
                if s_ <= idx:
                    begin = i
                else:
                    break
            if begin is None:
                continue
            name = heads[begin][1].group(2).split("(")[0].rstrip(";:").lower()
            # qualified by file: short method names like Lock or DoPause exist in
            # several units, and matching them globally links unrelated commits
            routines.add(f"{path}::{name}")
    return files, routines


def build_of(clone: str, sha: str) -> str | None:
    return (git(clone, "show", f"{sha}:src/mormot.commit-num.inc") or "").strip() or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", required=True)
    parser.add_argument("--clone", required=True)
    parser.add_argument("--ref", default="origin/master",
                        help="branch to look ahead on")
    parser.add_argument("--look-ahead-days", type=int, default=4,
                        help="how far past the edition to look for successors")
    args = parser.parse_args()

    path = RAW_DIR / f"{args.edition}.json"
    payload = read_json(path)
    if not payload:
        print(f"error: {path} not found", file=sys.stderr)
        return 2

    head = payload.get("range", {}).get("head_sha") or payload["commits"][0]["sha"]
    until = (datetime.date.fromisoformat(args.edition)
             + datetime.timedelta(days=args.look_ahead_days)).isoformat()
    oldest = payload["commits"][-1]["sha"]
    # A date window silently drops the edition's own commits at the boundary, so walk
    # the revision range from the oldest commit of the edition and cut by date after.
    raw_log = git(args.clone, "log", "--no-merges", "--pretty=format:%H\t%aI\t%s",
                  f"{oldest}~1..{args.ref}") or git(
                  args.clone, "log", "--no-merges", "--pretty=format:%H\t%aI\t%s",
                  f"{oldest}..{args.ref}")
    later = []
    for line in raw_log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[1][:10] <= until:
            later.append((parts[0], parts[2]))
    later.reverse()                      # chronological
    order = {sha: i for i, (sha, _) in enumerate(later)}

    known = {c["sha"] for c in payload["commits"]}
    cache: dict[str, tuple[set[str], set[str]]] = {}
    annotated = 0

    for commit in payload["commits"]:
        sha = commit["sha"]
        files, routines = cache.setdefault(sha, touched_routines(args.clone, sha))
        successors = []
        here = order.get(sha)
        for other_sha, subject in later:
            if here is None or order.get(other_sha, -1) <= here:
                continue                 # only what landed strictly after this commit
            ofiles, oroutines = cache.setdefault(other_sha, touched_routines(args.clone, other_sha))
            same_routine = bool(routines & oroutines)
            if not (same_routine or (files & ofiles and FIX.search(subject))):
                continue
            successors.append({
                "sha": other_sha,
                "short_sha": other_sha[:8],
                "subject": subject,
                "build": build_of(args.clone, other_sha),
                "same_routine": same_routine,
                "looks_like_a_fix": bool(FIX.search(subject)),
                "in_this_edition": other_sha in known,
            })
        if successors:
            commit["superseded_by"] = successors[:6]
            annotated += 1

    payload["look_ahead"] = {
        "days": args.look_ahead_days,
        "head_at_annotation": head,
        "latest_build_seen": build_of(args.clone, later[-1][0]) if later else None,
    }
    write_json(path, payload)
    print(f"{annotated}/{len(payload['commits'])} commit(s) have a later commit touching "
          f"the same routines within {args.look_ahead_days} days")
    for c in payload["commits"]:
        for s in c.get("superseded_by", []):
            if s["looks_like_a_fix"] and s["same_routine"]:
                print(f"  {c['short_sha']} {c['subject'][:46]}")
                print(f"     -> {s['short_sha']} (build {s['build']}) {s['subject'][:46]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
