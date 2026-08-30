#!/usr/bin/env python3
"""Merge the per-commit findings produced by the matrix jobs into one edition payload.

Each matrix job reviews one commit and uploads its own JSON. This gathers them, keeps
the day's commit list honest (a job that crashed must not silently look like a commit
with no findings), and writes data/findings/<edition>.json for the validator.

    python scripts/collect_findings.py --edition 2026-08-29 --parts artifacts/
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from common import DATA, RAW_DIR, read_json, write_json

FINDINGS_DIR = DATA / "findings"
USAGE_DIR = DATA / "usage"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", required=True)
    parser.add_argument("--parts", required=True, help="directory holding <sha>.json parts")
    parser.add_argument("--shas", help="the commits this run was supposed to review "
                                       "(comma-separated). Needed when the run is a "
                                       "measurement rather than a dated edition: "
                                       "without it there is no data/raw payload to "
                                       "say which parts should exist, and a job that "
                                       "crashed would silently look like a clean day.")
    args = parser.parse_args()

    if args.shas:
        expected = [s.strip() for s in args.shas.split(",") if s.strip()]
    else:
        raw = read_json(RAW_DIR / f"{args.edition}.json") or {}
        expected = [c["sha"] for c in raw.get("commits", []) if not c.get("is_merge")]
        if not expected:
            # No payload and no list: fall back to what is on disk. Crashed jobs are
            # then invisible, so say so rather than printing a confident zero.
            expected = sorted({f.name.split(".")[0]
                               for f in pathlib.Path(args.parts).glob("*.json")})
            if expected:
                print(f"note: no data/raw/{args.edition}.json and no --shas; "
                      f"took the {len(expected)} sha(s) found in {args.parts}. "
                      f"A job that produced nothing cannot be detected this way.")

    findings, unverified, reviewed, missing, usage, notes = [], [], [], [], [], []
    for sha in expected:
        # A commit is hunted once and verified once per suspicion, so several parts can
        # carry the same sha. Accumulate; taking the last one silently dropped findings.
        parts = []
        for candidate in sorted(pathlib.Path(args.parts).rglob(f"{sha[:8]}*.json")):
            if candidate.name.endswith(".usage.json"):
                # Claude Code's execution log: a list of events, or the result object.
                # Keep the fields that answer "what did this commit cost".
                log = read_json(candidate)
                result = log if isinstance(log, dict) else (log[-1] if log else {})
                if isinstance(result, list):
                    result = result[-1] if result else {}
                usage.append({
                    "sha": sha,
                    "pass": "hunt" if ".hunt." in candidate.name else "verify",
                    "num_turns": result.get("num_turns"),
                    "duration_ms": result.get("duration_ms"),
                    "total_cost_usd": result.get("total_cost_usd"),
                    "model_usage": result.get("modelUsage"),
                    "is_error": result.get("is_error"),
                })
                continue
            part = read_json(candidate)
            if part is not None:
                parts.append(part)
        if not parts:
            missing.append(sha)          # the job failed: say so, do not imply "clean"
            continue
        for part in parts:
            findings += part.get("findings", []) or []
            unverified += part.get("unverified", []) or []
            if part.get("notes"):
                notes.append(f"{sha[:8]}: {part['notes']}")
        reviewed.append(sha)

    payload = {
        "schema": "mormot2-monitor/findings@1",
        "edition": args.edition,
        "reviewed_shas": reviewed,
        "findings": findings,
        "unverified": unverified,
    }
    said = []
    if missing:
        said.append("Not reviewed, the job did not produce a result: "
                    + ", ".join(s[:8] for s in missing))
    said += notes                       # refutations from the verify pass
    if said:
        payload["notes"] = " | ".join(said)[:600]
    write_json(FINDINGS_DIR / f"{args.edition}.json", payload)
    if usage:
        total = sum(u.get("total_cost_usd") or 0 for u in usage)
        turns = sum(u.get("num_turns") or 0 for u in usage)
        seconds = sum((u.get("duration_ms") or 0) for u in usage) / 1000
        write_json(USAGE_DIR / f"{args.edition}.json", {
            "edition": args.edition,
            "totals": {"commits": len({u["sha"] for u in usage}),
                       "sessions": len(usage), "cost_usd": round(total, 4),
                       "turns": turns, "seconds": round(seconds)},
            "commits": usage,
        })
        hunt = sum(u.get("total_cost_usd") or 0 for u in usage if u["pass"] == "hunt")
        print(f"usage: {len({u['sha'] for u in usage})} commit(s), {len(usage)} session(s), "
              f"{total:.2f} USD equivalent ({hunt:.2f} hunt / {total - hunt:.2f} verify), "
              f"{turns} turns, {seconds / 60:.0f} min")

    print(f"{len(reviewed)}/{len(expected)} commit(s) reviewed, "
          f"{len(findings)} finding(s), {len(unverified)} unverified")
    if missing:
        print(f"missing: {', '.join(s[:8] for s in missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
