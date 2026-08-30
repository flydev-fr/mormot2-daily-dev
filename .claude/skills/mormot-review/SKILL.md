---
name: mormot-review
description: Hunt security and regression defects in one upstream mORMot2 commit, treating the diff as the suspect, and emit a findings JSON where every claim carries the source that proves it. Use when reviewing a commit of synopse/mORMot2.
allowed-tools: Read, Grep, Glob, Bash(git *), Write
---

# Reviewing one mORMot2 commit

You are reviewing a single commit of `synopse/mORMot2`, an Object Pascal framework for
Delphi and FPC running in production backends. The working tree is checked out at that
commit. `$REVIEW_SHA` holds the commit, `$REVIEW_OUTPUT` the file to write.

## Where to look

The scope is the commit. Anything the diff can plausibly break is in scope — a defect
does not stop being a defect because it has no category.

These five recur in this codebase, so check them on every commit whatever else you find:

1. **lock-not-released** — a lock, critical section or RW lock acquired on a path that
   can leave without releasing it: an early `exit`, a raised exception with no
   `try..finally`, a `{$ifdef}` branch where the release is missing.
2. **try-finally-removed** — a `try..finally` that protected a resource and no longer
   does, or a resource acquired outside the `try` meant to protect it.
3. **length-arithmetic** — an index, offset, length or capacity that can overflow, wrap,
   go negative or run past the buffer. Signed and unsigned mixing counts: a `Qword`
   assigned into an `Int64` wraps negative, and a later `>=` guard then lets it through.
4. **signature-changed-callers-stale** — a published function, method or property whose
   signature or contract changed while a caller still assumes the old one.
5. **ifdef-asymmetry** — a fix on one platform branch missing from the other. Compare
   `mormot.core.os.posix.inc` with `mormot.core.os.windows.inc`, and
   `mormot.net.sock.posix.inc` with `mormot.net.sock.windows.inc`.

Then let the files decide what else deserves attention:

- **assembler** (`*.asmx64.inc`, `*.asmx86.inc`, `asm` blocks) — clobbered registers not
  in the clobber list, a wrong calling convention, stack misalignment, a branch that
  skips the epilogue. `check: asm-abi`.
- **crypto** (`src/crypt/`) — a reused IV or nonce, a comparison that stopped being
  constant time, a weakened or silently swapped key derivation, entropy taken from a
  non-cryptographic generator. `check: crypto-misuse`.
- **protocol and state machines** (`src/net/`, `mormot.net.http`, `.ws.`, `.tftp.`) — a
  transition that lets a state be reached out of order, unvalidated input reaching a
  header or a path, chunked and content-length disagreeing, a resource freed on one
  path of the machine and not the others. `check: protocol-state`.
- **memory and lifetime** (`fpcx64mm`, `mormot.core.data`, refcounted types) — a double
  free, a use after free, a refcount that no longer balances, a buffer reused after
  being handed away. `check: memory-lifetime`.
- **anything else you can prove** — use `check: other` and say what it is.

Style, naming, dead code and "this could be clearer" are not findings. The author writes
terse code on purpose. Performance is a finding only when the change makes something
unbounded, not when it is merely slower.

## The change under review

`$REVIEW_CONTEXT` holds the unit to review: the diff, then the full body of every
routine it touches. **Read that file first, and treat it as the change.**

Do not take the diff from `git show $REVIEW_SHA`. The two differ whenever the run is a
synthetic one -- a reversed fix, a replayed change -- and there `git show` hands you a
completely different commit. Use git freely for everything else: callers, history,
the other platform's `.inc`, the state of any file at `$REVIEW_SHA`.

## The diff is the suspect

Start from the assumption that this change is where the bug is. It is not a baseline to
be explained; it is the hypothesis to be attacked. Most of the time it will be clean —
but you find that out by trying to break it, not by looking for a reason to accept it.

**Account for every deletion.** Before anything else, list what the diff *removes* or
*weakens*, and say what each removed line was holding up:

- a `try`, a `finally`, or a line inside one
- an `UnLock`, `ReadUnLock`, `WriteUnLock`, `Release`, `Free`, `Close`
- a bounds test, an overflow clamp, a sign test, a nil test, a length check
- a `{$ifdef}` branch, or one side of a platform pair

For each, one sentence: *what invariant did that line maintain, and what now maintains
it?* If nothing does, that is your finding. If something does, quote it. A deletion you
did not mention is a deletion you did not check — every one of them must appear in your
answer, as a finding or as an accounted-for line.

Watch the substitutions too, not only the removals. `WriteUnLock` becoming `WriteLock`
in a `finally` reads as one word changed and is a deadlock. Read paired calls as pairs:
acquire/release, alloc/free, open/close, enter/leave.

## Method

1. Read `$REVIEW_CONTEXT` — the diff and the routines it touches.
2. **Read the whole body of every routine the diff touches.** A hunk never shows what
   the rest of the function already does. A clearing call on the first line, or a guard
   three lines above your hunk, changes the answer completely. Most false positives come
   from reasoning about Pascal semantics instead of reading the function.
3. On a signature change, find the callers before concluding. When the
   `tokensave_callers` / `tokensave_affected` tools are available, use them: they walk
   the call graph, so they catch what a text search misses — a call through an
   interface, a method reached by inheritance. Without them, fall back to
   `git grep -n "<symbol>" -- src test ex`, and say in `why_unproven` when a text
   search was all you had.

   The same tools are how you satisfy `reachability`: `tokensave_affected` on the
   changed symbol gives you the chain up to a public entry point. Quote the call you
   found — the validator checks that quote like any other.
4. On a platform-specific change, open the other branch's `.inc` and compare.

## The rule

**No finding ships without the code that proves it.**

Every finding carries `evidence`: path, sha, and the source quoted **verbatim** — copied
from the file, never retyped from memory. `scripts/validate_findings.py` reads that file
at that sha and rejects the finding when the quote is not in it. A reconstructed quote
fails exactly like an invented one.

Every finding carries `reachability`: the public entry point that reaches the defect,
and a verbatim quote of the call connecting them. No path, no finding — it goes to
`unverified` with what you were missing.

Then turn on yourself. For each candidate, spend one honest pass trying to **refute**
it: read the callers, read the guards above and below, look for the check you missed.
Write what you checked into `refuted_by`. Survives refutation → `proven`. Still believed
but not closed → `likely`. Refuted → drop it, silently.

Refutation applies to candidates you already raised. It is not a reason to raise none:
run it after the accounting pass above, never instead of it. Reporting nothing on a
commit that removes a lock release is the expensive failure here — a false positive
costs a human five minutes, a missed release corrupts a production server.

An empty result is a legitimate result once the accounting pass is done and every
deletion is accounted for. It is not the default.

## Output

Write JSON to `$REVIEW_OUTPUT`, conforming to `schema/findings.schema.json`, with this
commit's findings only. No prose around it. Touch no other file.
