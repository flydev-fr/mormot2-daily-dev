"""Deterministic, AI-free classification of upstream commits.

Two jobs:
  1. pre-annotate the raw payload so Jules starts from structured input;
  2. keep the site useful when an analysis run is missing or failed
     (entries are then rendered as "not reviewed yet").
"""

from __future__ import annotations

import re

from common import AREA_BY_PREFIX, NOISE_FILES, area_of_path, unit_of

PR_RE = re.compile(r"#(\d{2,6})")
MERGE_RE = re.compile(r"^Merge pull request #(\d+) from (.+?)/(.+)$")

# Patterns are prefix-friendly on purpose ("optimiz\w*" catches optimize/optimized/
# optimizing). Order matters: the first rule that matches wins.
RULES = [
    ("breaking", r"\b(breaking change|incompatib\w*|no longer\b|migration\b|"
                 r"changed signature|signature changed)"),
    ("security", r"\b(security\w*|vulnerab\w*|CVE-|exploit\w*|sanitiz\w*|spoof\w*|"
                 r"buffer overflow|timing attack|injection)"),
    ("deprecation", r"\b(deprecat\w*|obsolete\b|legacy removal)"),
    ("performance", r"\b(optimi[sz]\w*|faster\b|speed ?ups?\b|perf\b|performance\b|"
                    r"less contention|lockless\b|reduce[sd]? (the )?(alloc\w*|memory))"),
    ("fix", r"\b(fix(ed|es|ing)?\b|bugs?\b|regressions?\b|race condition|leaks?\b|"
            r"crash\w*|corrupt\w*|wrong\b|invalid\b|broken\b|workarounds?\b|GPF\b|"
            r"access violation)"),
    ("feature", r"\b(new\b|adds?\b|added\b|introduc\w*|implement\w*|support for|"
                r"now supports)"),
    ("compat", r"\b(delphi ?\d|fpc\b|compil\w*|linux\b|windows\b|bsd\b|android\b|"
               r"aarch64\b|win32\b|win64\b|cross-platform|PUREMORMOT2)"),
    ("tests", r"^(tests?|regression)\b|\b(unit ?tests?|coverage\b)"),
    ("docs", r"^docs?\b|\b(documentation\b|readme\b|typos?\b)"),
    ("refactor", r"\b(refactor\w*|rewritten\b|rewrote\b|moved\b|renam\w*|"
                 r"clean-?up\w*|no functional change|code style)"),
]

SEVERITY_RULES = [
    ("critical", r"\b(race condition|corrupt\w*|security\w*|vulnerab\w*|data loss|"
                 r"deadlock\w*|breaking change)"),
    ("high", r"\b(awful\b|serious\w*|major\b|crash\w*|leaks?\b|regressions?\b|GPF\b|"
             r"access violation|wrong result|infinite loop)"),
    ("medium", r"\b(fix(ed|es)?\b|new\b|adds?\b|added\b|optimi[sz]\w*|support\w*)"),
]


def _match(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def classify(subject: str, body: str = "", files: list[dict] | None = None) -> dict:
    text = f"{subject}\n{body}"
    category = "chore"
    for name, pattern in RULES:
        if _match(text, pattern):
            category = name
            break

    severity = "low"
    for name, pattern in SEVERITY_RULES:
        if _match(text, pattern):
            severity = name
            break
    if category in ("docs", "tests", "chore"):
        severity = "low"

    return {"category": category, "severity": severity}


def area_from_subject(subject: str) -> str | None:
    head = subject.split(":", 1)[0].strip().lower() if ":" in subject else ""
    if " " in head or len(head) > 12:
        return None
    return AREA_BY_PREFIX.get(head)


def annotate(commit: dict) -> dict:
    """Add heuristic fields to a fetched commit record (in place)."""
    subject = commit.get("subject", "")
    body = commit.get("body", "")
    files = [f for f in commit.get("files", []) if f["path"] not in NOISE_FILES]

    guess = classify(subject, body, files)
    areas = sorted({area_of_path(f["path"]) for f in files}) or ["Other"]
    subject_area = area_from_subject(subject)
    if subject_area and subject_area in areas:
        areas = [subject_area] + [a for a in areas if a != subject_area]
    elif subject_area:
        areas = [subject_area] + areas

    units = sorted({u for f in files if (u := unit_of(f["path"]))})

    merge = MERGE_RE.match(subject)
    pr = None
    if merge:
        pr = int(merge.group(1))
        guess["category"] = "chore"
        guess["severity"] = "low"
    else:
        found = PR_RE.search(subject)
        if found:
            pr = int(found.group(1))

    commit["guess"] = guess
    commit["areas"] = areas
    commit["units"] = units
    commit["pr"] = pr
    commit["is_merge"] = bool(merge) or len(commit.get("parents", [])) > 1
    return commit
