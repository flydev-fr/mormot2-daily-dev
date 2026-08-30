#!/usr/bin/env python3
"""Turn the hunt pass's suspicions into one verify job per suspicion.

The hunt pass is told to guess, so most of what it produces is wrong. Splitting it one
suspicion per session is what lets the verify pass actually read the surrounding code
instead of skimming twelve leads in one context -- and it means a clean day launches no
verify job at all.

    python scripts/plan_verify.py --suspicions suspicions/ --units units/
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

# GitHub caps a matrix at 256 entries. Hitting that means the hunt pass went haywire,
# so stop rather than quietly reviewing an arbitrary subset.
MAX_UNITS = 256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suspicions", required=True, help="directory of <sha>.json")
    parser.add_argument("--units", required=True, help="directory to write the units to")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()

    units_dir = pathlib.Path(args.units)
    units_dir.mkdir(parents=True, exist_ok=True)

    matrix, skipped = [], []
    for path in sorted(pathlib.Path(args.suspicions).rglob("*.json")):
        if path.name.endswith(".usage.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            skipped.append(f"{path.name}: {e}")
            continue
        # The FILE name, not the payload's sha. The hunt job names its output after the
        # commit the matrix gave it; the payload carries whatever tree was actually
        # checked out, which in reverse mode is the parent. Keying on the payload made
        # the verify job apply the parent step a second time and review the grandparent.
        sha = path.name.split(".")[0]
        review_sha = payload.get("sha") or sha
        items = payload.get("suspicions") or []

        # One defect reliably produces several suspicions -- same routine, different
        # wording. Verifying each separately costs a full session per duplicate and
        # returns the same finding N times. Keep the first per location.
        seen, kept = set(), []
        for suspicion in items:
            key = (suspicion.get("path"), suspicion.get("symbol") or "",
                   suspicion.get("line"))
            if key in seen:
                continue
            seen.add(key)
            kept.append(suspicion)

        for i, suspicion in enumerate(kept):
            unit_id = f"v{i}"
            (units_dir / f"{sha}.{unit_id}.json").write_text(
                json.dumps({"sha": sha, "review_sha": review_sha, "id": unit_id,
                            "suspicion": suspicion}, indent=2, ensure_ascii=False),
                encoding="utf-8")
            matrix.append({"sha": sha, "id": unit_id})
        dropped = len(items) - len(kept)
        print(f"{sha[:8]}: {len(kept)} suspicion(s)"
              + (f", {dropped} duplicate(s) merged" if dropped else "")
              + f", {len(payload.get('accounted') or [])} accounted")

    for line in skipped:
        print(f"warning: {line}", file=sys.stderr)

    if len(matrix) > MAX_UNITS:
        print(f"error: {len(matrix)} suspicions, over the {MAX_UNITS} matrix cap. "
              f"The hunt pass is producing noise -- look at it before spending on "
              f"verification.", file=sys.stderr)
        return 1

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"matrix={json.dumps(matrix)}\n")
            fh.write(f"count={len(matrix)}\n")
    print(f"\n{len(matrix)} suspicion(s) to verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
