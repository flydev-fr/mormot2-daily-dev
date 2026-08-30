---
name: mormot-verify
description: Second pass over one suspicion raised on a mORMot2 commit — prove it with quoted source and a reachable path, or refute it. Emits a findings JSON. Use when verifying a single suspicion from the hunt pass.
allowed-tools: Read, Grep, Glob, Bash(git *), Write
---

# Verifying one suspicion

A previous pass hunted this commit with no burden of proof and raised one suspicion.
It is in `$REVIEW_SUSPICION`. The tree is checked out at the commit, `$REVIEW_SHA`.
Write to `$REVIEW_OUTPUT`.

**Assume it is wrong.** The pass that raised it was told to guess, and most guesses are
wrong. Your job is to close the question one way or the other, not to be agreeable.
"Probably fine" is not an answer; neither is repeating the suspicion in longer words.

## The change under review

`$REVIEW_CONTEXT` holds the unit to review: the diff, then the full body of every
routine it touches. **Read that file first, and treat it as the change.**

Do not take the diff from `git show $REVIEW_SHA`. The two differ whenever the run is a
synthetic one -- a reversed fix, a replayed change -- and there `git show` hands you a
completely different commit. Use git freely for everything else: callers, history,
the other platform's `.inc`, the state of any file at `$REVIEW_SHA`.

## What to do

1. Read the **whole body** of every routine involved — not the hunk, not an excerpt.
   Most false positives die here: a clearing call on the first line, a guard three lines
   above, an `{$ifdef}` that makes the branch unreachable on this platform.
2. Look for the thing that would make it safe: the guard, the caller that never passes
   that value, the release on the other path, the overflow already clamped upstream.
   Spend your effort here first. If you find it, the suspicion is refuted — say so.
3. If you cannot refute it, prove it. Find the public entry point that reaches the
   defect and the call chain to it. `tokensave_affected` / `tokensave_callers` when
   available — they follow interfaces and inheritance, which a text search does not.
   Otherwise `git grep -n "<symbol>" -- src test ex`, and say so in `why_unproven`.
4. Quote the source, **verbatim**, copied from the file — never retyped from memory.
   `scripts/validate_findings.py` reads the file at that sha and rejects the finding
   when the quote is not in it. A reconstructed quote fails exactly like an invented one.

## Deciding

- **Refuted** — you found what makes it safe. Write `findings: []` and put one line in
  `notes` saying what refuted it. This is the expected outcome most of the time.
- **Proven** — evidence quoted, reachability quoted, and `refuted_by` recording the
  guards and callers you checked that did *not* save it. `confidence: proven`.
- **Believed but not closed** — real code smell, missing one link (a caller list, a
  platform build, runtime behaviour). `confidence: likely` if you have evidence and
  reachability; otherwise it goes to `unverified` with `why_unproven` naming exactly
  what you were missing.

Severity is about consequence, not about how clever the bug is. A lock never released
takes the server down; a wrong log line does not.

## Output

Write JSON to `$REVIEW_OUTPUT` against `schema/findings.schema.json`, covering this one
suspicion only. `reviewed_shas` holds `$REVIEW_SHA`. No prose around it. Touch no other
file.
