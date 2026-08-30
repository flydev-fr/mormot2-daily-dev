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
        sha = payload.get("sha") or path.name.split(".")[0]
        items = payload.get("suspicions") or []
        for i, suspicion in enumerate(items):
            unit_id = f"v{i}"
            (units_dir / f"{sha[:8]}.{unit_id}.json").write_text(
                json.dumps({"sha": sha, "id": unit_id, "suspicion": suspicion},
                           indent=2, ensure_ascii=False), encoding="utf-8")
            matrix.append({"sha": sha, "id": unit_id})
        print(f"{sha[:8]}: {len(items)} suspicion(s), "
              f"{len(payload.get('accounted') or [])} accounted")

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
