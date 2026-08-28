#!/usr/bin/env python3
"""Drive a Jules session that turns data/raw/<edition>.json into data/analysis/<edition>.json.

    python scripts/run_jules_analysis.py start --edition 2026-08-28
    python scripts/run_jules_analysis.py feedback --session 314159 --errors-file err.txt

`start` creates the session from PROMPT.md, waits for it to finish and reports the pull
request Jules opened. `feedback` re-opens the conversation with validation errors so
Jules can repair its own output, and waits again.

Environment:
  JULES_API_KEY      required
  JULES_SOURCE       optional, e.g. sources/github/flydev-fr/mormot2-monitor-dev
  GITHUB_REPOSITORY  owner/repo, used to resolve the source automatically (CI provides it)
  JULES_BRANCH       starting branch (default: main)
  JULES_TIMEOUT      seconds to wait for a session (default: 3600)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from common import RAW_DIR, ROOT, UPSTREAM, read_json
from jules_api import JulesClient, JulesError, pull_request_output

PROMPT_TEMPLATE = ROOT / "PROMPT.md"


def build_prompt(edition: str, raw_path: str, analysis_path: str, count: int) -> str:
    text = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    # Everything above the first '---' is documentation for humans, not for Jules.
    if "\n---\n" in text:
        text = text.split("\n---\n", 1)[1]
    return (text
            .replace("{{EDITION}}", edition)
            .replace("{{RAW_PATH}}", raw_path)
            .replace("{{ANALYSIS_PATH}}", analysis_path)
            .replace("{{COMMIT_COUNT}}", str(count))
            .replace("{{UPSTREAM}}", UPSTREAM)
            .strip())


def emit_outputs(**values) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def resolve_source(client: JulesClient) -> str:
    configured = os.environ.get("JULES_SOURCE")
    if configured:
        return configured
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        raise JulesError("Set JULES_SOURCE or GITHUB_REPOSITORY (owner/repo)")
    owner, name = repo.split("/", 1)
    return client.find_source(owner, name)


def report(session: dict) -> dict | None:
    pr = pull_request_output(session)
    print(f"\nsession : {session.get('url') or session.get('name')}")
    print(f"state   : {session.get('state')}")
    if pr:
        print(f"PR      : {pr['url']}")
        number = pr["url"].rstrip("/").rsplit("/", 1)[-1]
        emit_outputs(pr_url=pr["url"], pr_number=number)
    else:
        print("PR      : none reported by the session")
        emit_outputs(pr_url="", pr_number="")
    return pr


def cmd_start(args) -> int:
    edition = args.edition
    raw_path = f"data/raw/{edition}.json"
    analysis_path = f"data/analysis/{edition}.json"
    raw = read_json(RAW_DIR / f"{edition}.json")
    if not raw:
        print(f"error: {raw_path} not found — run fetch_commits.py first", file=sys.stderr)
        return 2
    count = len(raw.get("commits", []))
    if count == 0:
        print("no commits in the raw payload, nothing to analyse")
        emit_outputs(session_id="", pr_url="", pr_number="", skipped="true")
        return 0

    prompt = build_prompt(edition, raw_path, analysis_path, count)
    if args.dry_run:  # no API key, no network: just show what would be sent
        print(f"source  : {os.environ.get('JULES_SOURCE', '(resolved at run time)')}")
        print(f"edition : {edition} ({count} commits)\n\n{prompt}")
        return 0

    client = JulesClient()
    source = resolve_source(client)
    print(f"source  : {source}")
    print(f"edition : {edition} ({count} commits)")
    session = client.create_session(
        prompt=prompt,
        source=source,
        branch=os.environ.get("JULES_BRANCH", "main"),
        title=f"mORMot2 Daily — {edition}",
        automation_mode="AUTO_CREATE_PR",
    )
    session_id = session.get("id") or session.get("name", "").rsplit("/", 1)[-1]
    print(f"session : {session_id}")
    emit_outputs(session_id=session_id)

    timeout = int(os.environ.get("JULES_TIMEOUT", "3600"))
    try:
        final = client.wait(session_id, timeout_s=timeout)
    except JulesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        emit_outputs(pr_url="", pr_number="", failed="true")
        return 1
    report(final)
    return 0 if final.get("state") == "COMPLETED" else 1


def cmd_feedback(args) -> int:
    errors = pathlib.Path(args.errors_file).read_text(encoding="utf-8").strip()
    if not errors:
        print("no errors to report")
        return 0
    message = (
        "The analysis file you produced does not pass "
        "`python scripts/validate_analysis.py`. Fix these errors in the same branch "
        "and pull request, then run the validator again until it prints OK:\n\n"
        f"{errors[:6000]}\n\n"
        "Do not change the schema or the validator, and do not open a second pull "
        "request — amend the existing one."
    )
    client = JulesClient()
    client.send_message(args.session, message)
    print(f"feedback sent to session {args.session}")
    final = client.wait(args.session, timeout_s=int(os.environ.get("JULES_TIMEOUT", "3600")))
    report(final)
    return 0 if final.get("state") == "COMPLETED" else 1


def cmd_activities(args) -> int:
    client = JulesClient()
    for activity in client.list_activities(args.session, args.limit):
        print(json.dumps(activity, indent=2)[:2000])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="create and wait for the analysis session")
    start.add_argument("--edition", required=True)
    start.add_argument("--dry-run", action="store_true",
                       help="print the resolved prompt instead of calling the API")
    start.set_defaults(func=cmd_start)

    feedback = sub.add_parser("feedback", help="send validation errors back to a session")
    feedback.add_argument("--session", required=True)
    feedback.add_argument("--errors-file", required=True)
    feedback.set_defaults(func=cmd_feedback)

    acts = sub.add_parser("activities", help="dump recent session activities")
    acts.add_argument("--session", required=True)
    acts.add_argument("--limit", type=int, default=10)
    acts.set_defaults(func=cmd_activities)

    args = parser.parse_args()
    try:
        return args.func(args)
    except JulesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
