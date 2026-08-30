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
    args = parser.parse_args()

    raw = read_json(RAW_DIR / f"{args.edition}.json") or {}
    expected = [c["sha"] for c in raw.get("commits", []) if not c.get("is_merge")]

    findings, unverified, reviewed, missing, usage = [], [], [], [], []
    for sha in expected:
        part = None
        for candidate in pathlib.Path(args.parts).rglob(f"{sha[:8]}*.json"):
            if candidate.name.endswith(".usage.json"):
                # Claude Code's execution log: a list of events, or the result object.
                # Keep the fields that answer "what did this commit cost".
                log = read_json(candidate)
                result = log if isinstance(log, dict) else (log[-1] if log else {})
                if isinstance(result, list):
                    result = result[-1] if result else {}
                usage.append({
                    "sha": sha,
                    "num_turns": result.get("num_turns"),
                    "duration_ms": result.get("duration_ms"),
                    "total_cost_usd": result.get("total_cost_usd"),
                    "model_usage": result.get("modelUsage"),
                    "is_error": result.get("is_error"),
                })
                continue
            part = read_json(candidate)
        if part is None:
            missing.append(sha)          # the job failed: say so, do not imply "clean"
            continue
        findings += part.get("findings", []) or []
        unverified += part.get("unverified", []) or []
        reviewed.append(sha)

    payload = {
        "schema": "mormot2-monitor/findings@1",
        "edition": args.edition,
        "reviewed_shas": reviewed,
        "findings": findings,
        "unverified": unverified,
    }
    if missing:
        payload["notes"] = ("Not reviewed, the job did not produce a result: "
                            + ", ".join(s[:8] for s in missing))[:600]
    write_json(FINDINGS_DIR / f"{args.edition}.json", payload)
    if usage:
        total = sum(u.get("total_cost_usd") or 0 for u in usage)
        turns = sum(u.get("num_turns") or 0 for u in usage)
        seconds = sum((u.get("duration_ms") or 0) for u in usage) / 1000
        write_json(USAGE_DIR / f"{args.edition}.json", {
            "edition": args.edition,
            "totals": {"commits": len(usage), "cost_usd": round(total, 4),
                       "turns": turns, "seconds": round(seconds)},
            "commits": usage,
        })
        print(f"usage: {len(usage)} commit(s), {total:.2f} USD equivalent, "
              f"{turns} turns, {seconds / 60:.0f} min")

    print(f"{len(reviewed)}/{len(expected)} commit(s) reviewed, "
          f"{len(findings)} finding(s), {len(unverified)} unverified")
    if missing:
        print(f"missing: {', '.join(s[:8] for s in missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
