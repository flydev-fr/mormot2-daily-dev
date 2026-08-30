#!/usr/bin/env python3
"""Run the code review over one day of upstream commits, one commit per session.

One agent session per commit, on purpose: a bounded context reviewed properly beats a
25-commit prompt where the last ten get skimmed. Each session is cheap to cache and a
bad commit cannot poison the rest of the day.

Every run records what it consumed, so a week of this produces a real consumption
figure instead of an estimate.

    python scripts/run_review.py --edition 2026-08-29 --clone /path/to/mORMot2
    python scripts/run_review.py --edition 2026-08-29 --clone ... --dry-run
    python scripts/run_review.py --edition 2026-08-29 --clone ... --only 7dd5c8c

Environment:
  REVIEW_MODEL          model passed to --model (default: the Claude Code default)
  MAX_THINKING_TOKENS   thinking budget, billed as output. The single biggest cost knob.
  REVIEW_MAX_TURNS      per-commit turn cap (default 30)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

from common import DATA, RAW_DIR, ROOT, iso, read_json, utcnow, write_json

FINDINGS_DIR = DATA / "findings"
USAGE_DIR = DATA / "usage"
BRIEF = ROOT / ".claude" / "skills" / "mormot-review" / "SKILL.md"

# Version bookkeeping touched by every commit.
NOISE = {"src/mormot.commit.inc", "src/mormot.commit-num.inc"}
# Pascal routine header at column 0, which is how the implementation section is written.
ROUTINE = re.compile(r"^(function|procedure|constructor|destructor)\s+\S", re.IGNORECASE)


def git(clone: str, *args: str, binary: bool = False):
    r = subprocess.run(["git", "-C", clone, *args], capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def changed_line_numbers(clone: str, base: str, head: str, path: str) -> list[int]:
    """Line numbers touched in the post-image of this file."""
    diff = git(clone, "diff", "-U0", base, head, "--", path) or ""
    lines = []
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        lines.extend(range(start, start + max(count, 1)))
    return lines


def enclosing_routines(text: str, line_numbers: list[int]) -> list[tuple[str, int, int]]:
    """Full body of every routine containing a touched line.

    This is the whole point of the exercise: the reviewer must see the first line of
    the function, not just the hunk. A clearing call or a guard sitting above the diff
    is exactly what turns a plausible finding into a false positive.
    """
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if ROUTINE.match(l)]
    if not starts:
        return []
    out, seen = [], set()
    for n in line_numbers:
        idx = n - 1
        begin = None
        for s in starts:
            if s <= idx:
                begin = s
            else:
                break
        if begin is None or begin in seen:
            continue
        end = len(lines)
        for i in range(begin + 1, len(lines)):
            if lines[i].rstrip() == "end;":       # implementation end, column 0
                end = i + 1
                break
            if ROUTINE.match(lines[i]):           # next routine, body was a forward decl
                end = i
                break
        if begin <= idx < end:
            seen.add(begin)
            name = lines[begin].strip()[:120]
            out.append((name, begin + 1, end))
    return out


def build_context(clone: str, base: str, head: str, max_body_chars: int,
                  message: bool = True) -> tuple[str, list[str]]:
    """The review unit: the diff, then the full body of every routine it touches.

    The change reads base -> head. Reversing those two is how a known fix becomes the
    diff that introduced the bug -- and there `message` must be off, or the commit
    message hands the reviewer the answer.
    """
    NO = (":!src/mormot.commit.inc", ":!src/mormot.commit-num.inc")
    if message:
        diff = git(clone, "show", "-U12", "--format=%s%n%b", head, "--", *NO) or ""
    else:
        diff = git(clone, "diff", "-U12", base, head, "--", *NO) or ""
    numstat = git(clone, "diff", "--numstat", base, head) or ""
    paths = [c.split("\t")[2] for c in numstat.splitlines()
             if len(c.split("\t")) == 3 and c.split("\t")[2] not in NOISE]
    sources = [p for p in paths if p.endswith((".pas", ".inc", ".dpr"))]

    blocks, budget = [], max_body_chars
    for path in sources:
        text = git(clone, "show", f"{head}:{path}")
        if text is None or budget <= 0:
            continue
        for name, begin, end in enclosing_routines(
                text, changed_line_numbers(clone, base, head, path)):
            body = "\n".join(text.splitlines()[begin - 1:end])
            if len(body) > budget:
                body = body[:budget] + "\n{ ... body truncated ... }"
            budget -= len(body)
            blocks.append(f"--- {path}:{begin} — {name}\n{body}")
            if budget <= 0:
                break

    context = f"### diff\n\n```\n{diff}\n```\n"
    if blocks:
        context += ("\n### full body of every routine the diff touches\n"
                    "(read these, not just the hunks)\n\n```\n"
                    + "\n\n".join(blocks) + "\n```\n")
    return context, paths


def build_prompt(sha: str, subject: str, paths: list[str], edition: str,
                 out_path: str, context: str) -> str:
    brief = BRIEF.read_text(encoding="utf-8")
    if brief.startswith("---"):          # strip the skill frontmatter
        brief = brief.split("---", 2)[2]
    return (brief
            .replace("{{SHA}}", sha)
            .replace("{{SUBJECT}}", subject)
            .replace("{{EDITION}}", edition)
            .replace("$REVIEW_OUTPUT", out_path).replace("$REVIEW_SHA", sha)
            .replace("{{UNIT_PATH}}", ", ".join(paths) or "(none)")
            .strip() + "\n\n" + context)


def claude_command(prompt_file: str) -> list[str]:
    """Kept in one place: check the flags against `claude --help` on your version."""
    cmd = ["claude", "-p", f"@{prompt_file}", "--output-format", "json",
           "--max-turns", os.environ.get("REVIEW_MAX_TURNS", "30"),
           "--allowedTools", "Read,Grep,Glob,Bash,Write"]
    model = os.environ.get("REVIEW_MODEL")
    if model:
        cmd += ["--model", model]
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", required=True)
    parser.add_argument("--clone", required=True, help="mORMot2 working tree")
    parser.add_argument("--only", help="review just this sha")
    parser.add_argument("--reverse", action="store_true",
                        help="review each commit backwards: the diff that would have "
                             "INTRODUCED what it fixed. The only way to measure "
                             "detection on a bug whose answer is already known. The "
                             "commit message is dropped -- it names the bug.")
    parser.add_argument("--shas",
                        help="review these commits (comma-separated) instead of the "
                             "edition's. They need not belong to the edition, or to "
                             "any edition: this is how recall is measured against "
                             "commits whose bug is already known.")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the prompts and report their size, call nothing")
    parser.add_argument("--prepare", metavar="DIR",
                        help="write the per-commit context into DIR and stop. Used by "
                             "the workflow, where claude-code-action runs the session "
                             "itself, one matrix job per commit.")
    parser.add_argument("--max-body-chars", type=int, default=60000)
    args = parser.parse_args()

    if args.shas:
        commits = []
        for ref in (r.strip() for r in args.shas.split(",")):
            if not ref:
                continue
            sha = (git(args.clone, "rev-parse", "--verify", f"{ref}^{{commit}}") or "").strip()
            if not sha:
                print(f"error: {ref} is not a commit in {args.clone}", file=sys.stderr)
                return 2
            subject = (git(args.clone, "show", "-s", "--format=%s", sha) or "").strip()
            commits.append({"sha": sha, "subject": subject})
    else:
        raw = read_json(RAW_DIR / f"{args.edition}.json")
        if not raw:
            print(f"error: data/raw/{args.edition}.json not found", file=sys.stderr)
            return 2
        commits = [c for c in raw.get("commits", []) if not c.get("is_merge")]
    if args.only:
        commits = [c for c in commits if c["sha"].startswith(args.only)]
    if not commits:
        print("nothing to review")
        return 0

    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / ".review-tmp"
    tmp.mkdir(exist_ok=True)

    findings, unverified, reviewed, usage = [], [], [], []
    print(f"{args.edition}: {len(commits)} commit(s) to review\n")

    for i, commit in enumerate(commits, 1):
        sha, subject = commit["sha"], commit.get("subject", "")
        if args.reverse:
            # The tree that results is the parent's, which is a real commit: quotes
            # then re-check against it, and the finding names the state it is about.
            base = sha
            head = (git(args.clone, "rev-parse", "--verify", f"{sha}^") or "").strip()
            if not head:
                print(f"error: {sha[:8]} has no parent", file=sys.stderr)
                return 2
            sha, subject = head, "(not available)"
        else:
            base, head = f"{sha}^", sha
        context, paths = build_context(args.clone, base, head, args.max_body_chars,
                                       message=not args.reverse)
        out_path = tmp / f"{sha[:8]}.json"
        prompt = build_prompt(sha, subject, paths, args.edition, str(out_path), context)
        prompt_file = tmp / f"{sha[:8]}.prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        if args.prepare:
            target = pathlib.Path(args.prepare)
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{sha[:8]}.context.md").write_text(context, encoding="utf-8")
            (target / f"{sha[:8]}.subject.txt").write_text(subject, encoding="utf-8")
            print(f"{sha[:8]}: context {len(context) / 1024:.0f} Ko")
            continue

        print(f"[{i}/{len(commits)}] {sha[:8]} {subject[:64]}")
        print(f"          prompt {len(prompt) / 1024:.0f} Ko (~{len(prompt) / 3.3 / 1000:.0f} k tokens)")
        if args.dry_run:
            reviewed.append(sha)
            continue

        started = time.time()
        proc = subprocess.run(claude_command(str(prompt_file)), cwd=args.clone,
                              capture_output=True, text=True)
        elapsed = time.time() - started
        if proc.returncode != 0:
            print(f"          FAILED: {proc.stderr.strip()[:200]}")
            continue

        record = {"sha": sha, "seconds": round(elapsed, 1)}
        try:
            envelope = json.loads(proc.stdout)
            record.update({k: envelope.get(k) for k in
                           ("num_turns", "total_cost_usd", "usage", "duration_api_ms")})
        except json.JSONDecodeError:
            record["raw_stdout_head"] = proc.stdout[:400]
        usage.append(record)

        produced = read_json(out_path)
        if produced:
            findings += produced.get("findings", []) or []
            unverified += produced.get("unverified", []) or []
        reviewed.append(sha)
        print(f"          {len((produced or {}).get('findings', []) or [])} finding(s), "
              f"{record.get('num_turns', '?')} turns, {elapsed:.0f}s")

    payload = {
        "schema": "mormot2-monitor/findings@1",
        "edition": args.edition,
        "reviewed_shas": reviewed,
        "findings": findings,
        "unverified": unverified,
    }
    if not args.dry_run and not args.prepare:
        write_json(FINDINGS_DIR / f"{args.edition}.json", payload)
        write_json(USAGE_DIR / f"{args.edition}.json",
                   {"edition": args.edition, "generated_at": iso(utcnow()),
                    "model": os.environ.get("REVIEW_MODEL", "(default)"),
                    "max_thinking_tokens": os.environ.get("MAX_THINKING_TOKENS", "(default)"),
                    "commits": usage})
        print(f"\n{len(findings)} finding(s), {len(unverified)} unverified")
        print(f"wrote data/findings/{args.edition}.json and data/usage/{args.edition}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
