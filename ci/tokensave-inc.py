#!/usr/bin/env python3
"""Teach tokensave that .inc files are Object Pascal.

This used to be a context diff. tokensave's extension lists move, and a context diff
that stops applying fails the whole review run for a reason that has nothing to do
with the review. So: match the lists by shape rather than by surrounding lines, and
rewrite each list whole, which makes running twice a no-op.

Why .inc at all: mORMot2 keeps 61k lines (11% of src/) in 15 include files, the whole
posix/windows OS layer among them. They are fragments rather than compilable units,
so tree-sitter wraps them in ERROR nodes and still finds the routines inside.

Do not send this upstream as is: .inc also belongs to PHP and to several assemblers.

    python ci/tokensave-inc.py <tokensave checkout>
"""
import pathlib
import re
import sys

# The Pascal extension list, in either syntax tokensave uses: an array literal
# ("pas", "pp", "dpr") or a match arm ("pas" | "pp" | "dpr").
KNOWN = ("pp", "dpr", "lpr", "inc")
LISTS = (
    (", ", re.compile(r'"pas"((?:\s*,\s*"(?:%s)")+)' % "|".join(KNOWN))),
    (" | ", re.compile(r'"pas"((?:\s*\|\s*"(?:%s)")+)' % "|".join(KNOWN))),
)

TARGETS = ("src/extraction/pascal_extractor.rs", "src/db/queries/mod.rs", "src/hooks.rs")


def extend(text: str) -> tuple[str, int]:
    """Rewrite every Pascal extension list so it also carries "inc"."""
    hits = 0

    def rewriter(sep):
        def sub(m):
            nonlocal hits
            found = re.findall(r'"(\w+)"', m.group(1))
            if "inc" in found:
                return m.group(0)
            hits += 1
            return '"pas"' + "".join(f'{sep}"{e}"' for e in found + ["inc"])
        return sub

    for sep, pattern in LISTS:
        text = pattern.sub(rewriter(sep), text)
    return text, hits


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    changed, already, unknown = 0, 0, []
    for name in TARGETS:
        path = root / name
        if not path.exists():
            unknown.append(f"{name} (gone from tokensave)")
            continue
        text = path.read_text(encoding="utf-8")
        out, n = extend(text)
        if n and out != text:
            path.write_text(out, encoding="utf-8")
            print(f"{name}: {n} list(s) extended")
            changed += n
        elif '"inc"' in text:
            print(f'{name}: already carries "inc", left alone')
            already += 1
        else:
            unknown.append(name)

    for name in unknown:
        print(f"warning: {name} has no Pascal extension list I recognise")
    if not changed and not already:
        print("error: nothing was patched -- tokensave's lists have moved, "
              "see ci/README.md", file=sys.stderr)
        return 1
    if unknown:
        # Partial is worse than none: the graph would look fine and quietly miss a
        # third of the framework. Fail, and let the probe step stay honest.
        print(f"error: {len(unknown)} target(s) not patched", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
