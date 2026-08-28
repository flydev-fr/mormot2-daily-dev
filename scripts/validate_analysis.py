#!/usr/bin/env python3
"""Validate an analysis payload against the contract in schema/analysis.schema.json.

Structural validation uses `jsonschema` when installed; the semantic checks
(SHAs resolve to real commits, coverage, no copy-pasted commit subjects) always
run. Errors are printed one per line so they can be fed straight back to Jules.

    python scripts/validate_analysis.py data/analysis/2026-08-28.json
    python scripts/validate_analysis.py --edition 2026-08-28 --errors-file err.txt
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from common import (
    ACTIONS, ANALYSIS_DIR, ANALYSIS_SCHEMA, CATEGORIES, RAW_DIR, SCHEMA_FILE,
    SEVERITIES, read_json,
)

MIN_COVERAGE = 0.9  # share of non-merge upstream commits that must be reviewed


def structural_errors(payload: dict) -> list[str]:
    schema = read_json(SCHEMA_FILE)
    if not schema:
        return ["schema/analysis.schema.json is missing or invalid"]
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return _fallback_structural(payload)
    validator = jsonschema.Draft7Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(payload), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path) or "(root)"
        out.append(f"{where}: {err.message}")
    return out[:40]


def _fallback_structural(payload: dict) -> list[str]:
    errors = []
    for field in ("schema", "edition", "edition_title", "intro", "tldr", "entries"):
        if field not in payload:
            errors.append(f"(root): missing required field '{field}'")
    if payload.get("schema") != ANALYSIS_SCHEMA:
        errors.append(f"schema: must be '{ANALYSIS_SCHEMA}'")
    if not isinstance(payload.get("tldr"), list) or not payload.get("tldr"):
        errors.append("tldr: must be a non-empty array of strings")
    for i, entry in enumerate(payload.get("entries") or []):
        for field in ("sha", "headline", "category", "severity",
                      "what_changed", "impact", "action", "confidence"):
            if not entry.get(field):
                errors.append(f"entries/{i}: missing required field '{field}'")
        if entry.get("category") and entry["category"] not in CATEGORIES:
            errors.append(f"entries/{i}/category: '{entry['category']}' is not one of "
                          f"{', '.join(CATEGORIES)}")
        if entry.get("severity") and entry["severity"] not in SEVERITIES:
            errors.append(f"entries/{i}/severity: '{entry['severity']}' is not one of "
                          f"{', '.join(SEVERITIES)}")
        if entry.get("action") and entry["action"] not in ACTIONS:
            errors.append(f"entries/{i}/action: '{entry['action']}' is not one of "
                          f"{', '.join(ACTIONS)}")
    return errors[:40]


def semantic_errors(payload: dict, raw: dict | None) -> list[str]:
    errors: list[str] = []
    entries = payload.get("entries") or []

    if raw:
        if payload.get("edition") != raw.get("edition"):
            errors.append(f"edition: '{payload.get('edition')}' does not match the raw "
                          f"payload edition '{raw.get('edition')}'")
        by_sha = {c["sha"]: c for c in raw.get("commits", [])}
        short_map = {c["sha"][:8]: c["sha"] for c in raw.get("commits", [])}
        reviewed = set()
        for i, entry in enumerate(entries):
            sha = entry.get("sha", "")
            full = sha if sha in by_sha else short_map.get(sha[:8])
            if not full:
                errors.append(f"entries/{i}/sha: '{sha}' is not a commit of this "
                              f"edition; use the full sha from the raw payload")
                continue
            if full in reviewed:
                errors.append(f"entries/{i}/sha: duplicate entry for {sha[:8]}")
            reviewed.add(full)
            subject = (by_sha[full].get("subject") or "").strip().lower()
            headline = (entry.get("headline") or "").strip().lower()
            if headline and headline == subject:
                errors.append(f"entries/{i}/headline: identical to the commit subject; "
                              f"rewrite it in plain English for a reader who does not "
                              f"know the codebase")

        expected = [c for c in raw.get("commits", []) if not c.get("is_merge")]
        if expected:
            coverage = len(reviewed & {c["sha"] for c in expected}) / len(expected)
            if coverage < MIN_COVERAGE:
                missing = [c["sha"][:8] for c in expected if c["sha"] not in reviewed][:12]
                errors.append(
                    f"entries: only {coverage:.0%} of the {len(expected)} non-merge "
                    f"commits are covered (minimum {MIN_COVERAGE:.0%}). Missing: "
                    f"{', '.join(missing)}")

    for i, entry in enumerate(entries):
        if entry.get("action") in ("upgrade-recommended", "migration-required") \
                and not entry.get("action_detail"):
            errors.append(f"entries/{i}/action_detail: required when action is "
                          f"'{entry['action']}'")
        if entry.get("category") in ("breaking", "security") \
                and entry.get("severity") == "low":
            errors.append(f"entries/{i}: category '{entry['category']}' with severity "
                          f"'low' is contradictory")
    return errors


def validate(path: pathlib.Path, raw_path: pathlib.Path | None) -> list[str]:
    payload = read_json(path)
    if payload is None:
        return [f"{path}: file is missing or is not valid JSON"]
    raw = read_json(raw_path) if raw_path and raw_path.exists() else None
    errors = structural_errors(payload)
    errors += semantic_errors(payload, raw)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", help="path to data/analysis/<edition>.json")
    parser.add_argument("--edition", help="validate data/analysis/<edition>.json")
    parser.add_argument("--all", action="store_true", help="validate every analysis file")
    parser.add_argument("--raw", help="raw payload to check against "
                                      "(default: data/raw/<same name>)")
    parser.add_argument("--errors-file", help="also write the error list to this file")
    args = parser.parse_args()

    targets: list[pathlib.Path] = []
    if args.all:
        targets = sorted(ANALYSIS_DIR.glob("*.json"))
    elif args.edition:
        targets = [ANALYSIS_DIR / f"{args.edition}.json"]
    elif args.path:
        targets = [pathlib.Path(args.path)]
    else:
        parser.error("give a path, --edition or --all")

    all_errors: list[str] = []
    for target in targets:
        raw_path = pathlib.Path(args.raw) if args.raw else RAW_DIR / target.name
        errors = validate(target, raw_path)
        if errors:
            print(f"FAIL {target.name}")
            for err in errors:
                print(f"  - {err}")
            all_errors += [f"{target.name}: {e}" for e in errors]
        else:
            print(f"OK   {target.name}")

    if args.errors_file:
        pathlib.Path(args.errors_file).write_text("\n".join(all_errors), encoding="utf-8")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
