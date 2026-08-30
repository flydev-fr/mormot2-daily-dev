#!/usr/bin/env python3
"""Validate a findings payload, and re-check every quote against the real source.

The schema says a finding must carry verbatim evidence. This script is what makes
that binding: it fetches each quoted file at the stated sha and rejects the finding
when the quote is not in it, character for character (whitespace normalised, since
a model reflows indentation). A fabricated claim cannot reach the site.

    python scripts/validate_findings.py --edition 2026-08-26
    python scripts/validate_findings.py --edition 2026-08-26 --clone /path/to/mORMot2
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
import urllib.request

from common import DATA, RAW_DIR, UPSTREAM, read_json

FINDINGS_DIR = DATA / "findings"
SCHEMA = pathlib.Path(__file__).resolve().parent.parent / "schema" / "findings.schema.json"
FINDINGS_SCHEMA = "mormot2-monitor/findings@1"


def normalise(text: str) -> str:
    """Collapse whitespace so re-indentation does not fail an honest quote."""
    return re.sub(r"\s+", " ", text or "").strip()


class Source:
    """Reads a file at a given sha, from a local clone when available."""

    def __init__(self, clone: str | None):
        self.clone = clone
        self.cache: dict[tuple[str, str], str | None] = {}

    def read(self, path: str, sha: str) -> str | None:
        key = (path, sha)
        if key in self.cache:
            return self.cache[key]
        text = self._from_clone(path, sha) if self.clone else None
        if text is None:
            text = self._from_github(path, sha)
        self.cache[key] = text
        return text

    def _from_clone(self, path: str, sha: str) -> str | None:
        r = subprocess.run(["git", "-C", self.clone, "show", f"{sha}:{path}"],
                           capture_output=True)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None

    def _from_github(self, path: str, sha: str) -> str | None:
        url = f"https://raw.githubusercontent.com/{UPSTREAM}/{sha}/{path}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception:
            return None


def structural_errors(payload: dict) -> list[str]:
    schema = read_json(SCHEMA)
    if not schema:
        return ["schema/findings.schema.json is missing or invalid"]
    try:
        import jsonschema  # type: ignore
        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    except Exception as exc:
        return [f"(schema): jsonschema could not run ({exc.__class__.__name__}: {exc})"]
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors][:40]


def evidence_errors(payload: dict, source: Source) -> list[str]:
    """The heart of it: every quote must exist in the source at that sha."""
    errors = []
    for i, finding in enumerate(payload.get("findings") or []):
        quotes = [(f"entries/{i}/evidence/{j}", e.get("path"), e.get("sha"), e.get("quote"))
                  for j, e in enumerate(finding.get("evidence") or [])]
        reach = finding.get("reachability") or {}
        if reach.get("path_quote"):
            quotes.append((f"entries/{i}/reachability", 
                           reach.get("path_path") or (finding.get("evidence") or [{}])[0].get("path"),
                           reach.get("path_sha") or finding.get("sha"),
                           reach.get("path_quote")))
        for where, path, sha, quote in quotes:
            if not (path and sha and quote):
                errors.append(f"{where}: path, sha and quote are all required")
                continue
            text = source.read(path, sha)
            if text is None:
                errors.append(f"{where}: cannot read {path} at {sha[:8]} — "
                              f"wrong path or wrong sha")
                continue
            if normalise(quote) not in normalise(text):
                errors.append(f"{where}: the quoted code is not in {path} at {sha[:8]}. "
                              f"Quote verbatim from the file, do not paraphrase or "
                              f"reconstruct it: {quote[:90]!r}")
    return errors


def semantic_errors(payload: dict, raw: dict | None) -> list[str]:
    errors = []
    if raw:
        known = {c["sha"] for c in raw.get("commits", [])}
        short = {s[:8]: s for s in known}
        expected = {c["sha"] for c in raw.get("commits", []) if not c.get("is_merge")}
        reviewed = set()
        for sha in payload.get("reviewed_shas", []):
            full = sha if sha in known else short.get(sha[:8])
            if not full:
                errors.append(f"reviewed_shas: {sha[:8]} is not a commit of this edition")
            else:
                reviewed.add(full)
        missing = expected - reviewed
        if missing:
            errors.append(f"reviewed_shas: {len(missing)} non-merge commit(s) of the "
                          f"edition were not reviewed: "
                          f"{', '.join(sorted(s[:8] for s in missing)[:10])}")
        for i, finding in enumerate(payload.get("findings") or []):
            sha = finding.get("sha", "")
            if sha not in known and short.get(sha[:8]) is None:
                errors.append(f"entries/{i}/sha: {sha[:8]} is not a commit of this edition")
    for i, finding in enumerate(payload.get("findings") or []):
        if finding.get("confidence") == "proven" and not finding.get("refuted_by"):
            errors.append(f"entries/{i}: confidence 'proven' requires refuted_by — a "
                          f"finding is only proven once the second pass failed to refute it")
        if (finding.get("reachability") or {}).get("reachable_from", "").strip().lower() \
                in ("internal only", "internal", "none", "n/a"):
            errors.append(f"entries/{i}/reachability: not reachable from a public entry "
                          f"point, so it belongs in 'unverified', not in 'findings'")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    parser.add_argument("--edition")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--clone", help="local mORMot2 clone, avoids network lookups")
    parser.add_argument("--errors-file")
    args = parser.parse_args()

    if args.all:
        targets = sorted(FINDINGS_DIR.glob("*.json"))
    elif args.edition:
        targets = [FINDINGS_DIR / f"{args.edition}.json"]
    elif args.path:
        targets = [pathlib.Path(args.path)]
    else:
        parser.error("give a path, --edition or --all")

    source = Source(args.clone)
    all_errors: list[str] = []
    for target in targets:
        payload = read_json(target)
        if payload is None:
            all_errors.append(f"{target.name}: missing or not valid JSON")
            print(f"FAIL {target.name}: missing or not valid JSON")
            continue
        raw = read_json(RAW_DIR / target.name)
        errors = (structural_errors(payload)
                  + semantic_errors(payload, raw)
                  + evidence_errors(payload, source))
        if errors:
            print(f"FAIL {target.name}")
            for e in errors:
                print(f"  - {e}")
            all_errors += [f"{target.name}: {e}" for e in errors]
        else:
            n = len(payload.get("findings") or [])
            print(f"OK   {target.name} — {n} finding(s), every quote re-checked "
                  f"against the source")

    if args.errors_file:
        pathlib.Path(args.errors_file).write_text("\n".join(all_errors), encoding="utf-8")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
