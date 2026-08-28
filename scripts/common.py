"""Shared helpers for the mORMot2 monitor pipeline."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_DIR = DATA / "raw"
ANALYSIS_DIR = DATA / "analysis"
STATE_FILE = DATA / "state.json"
SCHEMA_FILE = ROOT / "schema" / "analysis.schema.json"
SITE_SRC = ROOT / "site"
SITE_OUT = ROOT / "_site"

UPSTREAM = os.environ.get("UPSTREAM_REPO", "synopse/mORMot2")
SITE_TITLE = "mORMot2 Daily"
SITE_TAGLINE = "What changed in mORMot2, in plain English."
# Overridden by the SITE_BASE_URL env var in CI (used for RSS absolute links).
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")

RAW_SCHEMA = "mormot2-monitor/raw@1"
ANALYSIS_SCHEMA = "mormot2-monitor/analysis@1"

# Files touched by every single upstream commit: pure version bookkeeping.
NOISE_FILES = {"src/mormot.commit.inc", "src/mormot.commit-num.inc"}

CATEGORIES = [
    "breaking",
    "security",
    "fix",
    "feature",
    "performance",
    "deprecation",
    "refactor",
    "compat",
    "tests",
    "docs",
    "chore",
]

SEVERITIES = ["critical", "high", "medium", "low"]
ACTIONS = ["none", "review", "upgrade-recommended", "migration-required"]


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def iso(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> _dt.datetime:
    value = (value or "").replace("Z", "+00:00")
    try:
        dt = _dt.datetime.fromisoformat(value)
    except ValueError:
        return utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def read_json(path: pathlib.Path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_state() -> dict:
    state = read_json(STATE_FILE, {}) or {}
    state.setdefault("last_run", None)
    state.setdefault("last_commit_date", None)
    state.setdefault("seen_shas", [])
    return state


def save_state(state: dict) -> None:
    state["seen_shas"] = list(dict.fromkeys(state.get("seen_shas", [])))[-800:]
    write_json(STATE_FILE, state)


def unit_of(path: str) -> str | None:
    """Return the Pascal unit name for a source path, if any."""
    name = path.rsplit("/", 1)[-1]
    if name.startswith("mormot.") and name.endswith((".pas", ".inc")):
        return re.sub(r"\.(pas|inc)$", "", name)
    return None


AREA_BY_DIR = {
    "src/core": "Core",
    "src/crypt": "Crypto",
    "src/db": "Database",
    "src/net": "Network",
    "src/orm": "ORM",
    "src/rest": "REST",
    "src/soa": "SOA",
    "src/app": "App",
    "src/ddd": "DDD",
    "src/lib": "External libs",
    "src/misc": "Misc",
    "src/script": "Script",
    "src/tools": "Tools",
    "src/ui": "UI",
    "test": "Tests",
    "ex": "Samples",
    "doc": "Docs",
    "docs": "Docs",
    "packages": "Packages",
    "res": "Resources",
    "static": "Static libs",
}

# Upstream commit-subject prefixes ("net: ...", "orm: ...").
AREA_BY_PREFIX = {
    "core": "Core",
    "crypt": "Crypto",
    "db": "Database",
    "net": "Network",
    "orm": "ORM",
    "rest": "REST",
    "soa": "SOA",
    "app": "App",
    "ddd": "DDD",
    "lib": "External libs",
    "misc": "Misc",
    "script": "Script",
    "tools": "Tools",
    "ui": "UI",
    "mvc": "MVC",
    "test": "Tests",
    "tests": "Tests",
    "doc": "Docs",
    "docs": "Docs",
    "ex": "Samples",
    "all": "Cross-cutting",
    "misc.": "Misc",
}


def area_of_path(path: str) -> str:
    for prefix, area in AREA_BY_DIR.items():
        if path == prefix or path.startswith(prefix + "/"):
            return area
    return "Other"


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "item"


def short(sha: str) -> str:
    return (sha or "")[:8]
