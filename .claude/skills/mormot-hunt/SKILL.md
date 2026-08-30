---
name: mormot-hunt
description: First pass over one mORMot2 commit — find everything that could break, with no burden of proof. Emits a suspicions JSON for the verify pass. Use when hunting defects in a commit of synopse/mORMot2.
allowed-tools: Read, Grep, Glob, Bash(git *), Write
---

# Hunting one mORMot2 commit

One commit of `synopse/mORMot2`, an Object Pascal framework running in production
backends. The tree is checked out at that commit. `$REVIEW_SHA` is the commit,
`$REVIEW_OUTPUT` the file to write.

**Your job is recall, not accuracy.** Another pass will take each of your suspicions,
read the code around it, and kill the ones that are wrong. That pass is good at it.
What it cannot do is find something you never mentioned.

So: no evidence requirement, no reachability, no refutation. A suspicion you are 30 %
sure of is worth writing down. A suspicion you cannot justify is worth writing down if
the shape of the change bothers you. The cost of a wrong one is a few minutes of the
next pass; the cost of a missing one is a defect in production.

Do not, however, pad. Twelve is the cap and reaching it means you are guessing at
random. Style, naming, dead code and "this could be clearer" are not suspicions.

## The change under review

`$REVIEW_CONTEXT` holds the unit to review: the diff, then the full body of every
routine it touches. **Read that file first, and treat it as the change.**

Do not take the diff from `git show $REVIEW_SHA`. The two differ whenever the run is a
synthetic one -- a reversed fix, a replayed change -- and there `git show` hands you a
completely different commit. Use git freely for everything else: callers, history,
the other platform's `.inc`, the state of any file at `$REVIEW_SHA`.

## Account for every deletion

Go through what the diff **removes or weakens** before anything else:

- a `try`, a `finally`, or a line inside one
- an `UnLock`, `ReadUnLock`, `WriteUnLock`, `Release`, `Free`, `Close`
- a bounds test, an overflow clamp, a sign test, a nil test, a length check
- a `{$ifdef}` branch, or one side of a platform pair

For each: what invariant did that line hold, and what holds it now? Nothing → suspicion.
Something → put it in `accounted` with the one line that replaces it, so the next pass
does not redo the work.

Read substitutions as carefully as removals. `WriteUnLock` becoming `WriteLock` inside a
`finally` is one word and a deadlock. Read paired calls as pairs: acquire/release,
alloc/free, open/close, enter/leave. If the diff moved a line, ask what it moved across.

## Then the recurring shapes

1. **lock-not-released** — acquired on a path that can leave without releasing: an early
   `exit`, an exception with no `try..finally`, an `{$ifdef}` branch missing the release.
2. **length-arithmetic** — an index, offset, length or capacity that can overflow, wrap,
   go negative or run past the buffer. A `Qword` into an `Int64` wraps negative, and a
   later `>=` guard then lets it through.
3. **signature-changed-callers-stale** — a signature or contract that changed while a
   caller still assumes the old one.
4. **ifdef-asymmetry** — a fix on one platform branch missing from the other. Compare
   `mormot.core.os.posix.inc` with `mormot.core.os.windows.inc`,
   `mormot.net.sock.posix.inc` with `mormot.net.sock.windows.inc`.

Then let the files decide: `asm` blocks (clobbered registers, calling convention, stack
alignment, a branch skipping the epilogue), `src/crypt/` (reused IV or nonce, a
comparison that stopped being constant time, a weakened KDF, non-cryptographic entropy),
`src/net/` (a state reachable out of order, unvalidated input reaching a header or path,
chunked and content-length disagreeing), memory and lifetime (double free, use after
free, refcount that no longer balances, buffer reused after being handed away).

Anything the diff can plausibly break is in scope. A defect does not stop being one
because it has no category.

## Read before you judge

Read the **whole body** of every routine the diff touches, not the hunk. A clearing call
on the first line or a guard three lines above changes the answer. This is the one place
where reading more makes you find *fewer* things, and those things were wrong anyway.

Where `tokensave_callers` / `tokensave_affected` are available, use them on any changed
symbol — they walk the call graph, so they catch a call through an interface or reached
by inheritance that a text search misses. Otherwise `git grep -n "<symbol>" -- src test ex`.

## Output

Write JSON to `$REVIEW_OUTPUT` against `schema/suspicions.schema.json`. No prose around
it. Touch no other file.

An empty `suspicions` list is allowed only when `accounted` shows you went through the
deletions and found each one covered. Empty on both is a claim that the diff removes
nothing and adds nothing risky — make sure that is true before writing it.
