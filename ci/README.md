# ci/

`tokensave-inc.patch` — teaches tokensave that `.inc` files are Object Pascal.

Upstream maps `.pas`, `.pp`, `.dpr` and `.lpr` to the Pascal extractor and leaves
`.inc` as "Other". mORMot2 keeps 61,642 lines across 15 `.inc` files — 11% of `src/`,
and the whole platform layer: `mormot.core.os.posix.inc` (414 routines),
`mormot.core.os.windows.inc` (333), `mormot.net.sock.posix.inc`,
`mormot.net.sock.windows.inc`, plus the x86/x64 assembler includes. Without the patch
the code graph is blind exactly where the posix/windows asymmetries live, which is one
of the things the review looks for.

Three call sites: the extractor's extension list, the display-language map, and the
hook's code-extension list.

**Measured, on the real files.** The tree-sitter Pascal grammar was compiled
standalone and run against mORMot2's includes. Routines recognised versus ERROR nodes:

| file | routines | ERROR nodes |
|---|---|---|
| `mormot.core.threads.pas` (a normal unit, for reference) | 630 | 91 |
| `mormot.core.os.posix.inc` | 764 | 53 |
| `mormot.core.os.windows.inc` | 612 | 45 |
| `mormot.net.sock.posix.inc` | 168 | 7 |
| `mormot.core.rtti.fpc.inc` | 153 | 66 |
| `mormot.core.base.asmx64.inc` | 10 | 912 |

The include files parse at least as cleanly as a normal unit — the two OS-layer files
alone bring 1,376 routines into the graph that were invisible before. Their root node
is `ERROR`, which is expected and harmless: a fragment has no `unit` header, so the
grammar flags the edges and parses the body.

The exception is the assembler includes. `mormot.core.base.asmx64.inc` yields 912 ERROR
nodes for 10 dubious routines: it is x86-64 assembly, not Pascal, and there is nothing
to extract. The extractor dispatches on extension, so it cannot skip them by name.
They are noise rather than a problem, but `*.asmx86.inc` and `*.asmx64.inc` are worth
excluding if tokensave grows a per-project ignore list.

The workflow still probes the graph after indexing, on `PosixOpen` — a symbol that
exists only in `mormot.core.os.posix.inc`. Parsing well and landing in the database are
two different claims, and only the second one matters here.

**Do not send this upstream as is.** `.inc` also belongs to PHP and to assemblers, so
claiming it globally for Pascal is right for this repository and wrong in general. An
upstream version would key it on the project, or sniff the content.
