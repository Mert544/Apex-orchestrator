# Covering-scope reachability — closing the fake-green hole (2026-07-08)

## The hole (found on a REAL external run, not in theory)

The external-validation fleet run (see `external-validation-fleet.md`) produced
one fake green: on `packaging` 26.2, 31 moves were stamped "verified" while the
real suite went from 61,513 passing to 401 failing. One of the two root causes
was the transform itself (fixed in `fdda01f`); the other was **impact scoping**:

`covering_test_files` matched a test to a changed module only by the module's
own dotted path and its parent packages. Two import shapes that genuinely
EXECUTE the changed module slipped through:

1. **Child import** — `tests/test_licenses.py` imports
   `packaging.licenses._spdx`. Importing that submodule executes
   `packaging/licenses/__init__.py` on the way — yet a change to that
   `__init__` found *no* covering test, so the per-move verify ran nothing
   and the move passed "verified".
2. **Transitive import** — a test imports `pkg.api`, and `api` itself does
   `from pkg._impl import f`. A change to `_impl` is exercised by that test,
   but no import statement in the test names `_impl`. (Also pinned for years
   as a known blind spot in `test_measurement_soundness_eyml.py` —
   `test_covering_selection_misses_reexport_indirection`.)

Under-approximation here is the one direction Apex must never err in: it turns
"verified" into a lie. (Over-approximation just runs extra tests.)

## The fix — close the class, not the instance

New module `app/engine/import_reach.py`:

- builds the project's own **import graph** (absolute imports, **relative
  imports resolved** against each module's package position, plus the implicit
  *execute-your-ancestor-`__init__`* edges);
- computes, for a changed module, the **reverse reachability set** — every
  project module whose import would execute it — and returns their exact
  import names (raw + source-root-stripped for `src/` layouts);
- additionally returns **package prefixes**: for every covered package
  `__init__`, importing *anything* under the prefix executes it — the belt to
  the graph's suspenders for descendants the graph cannot index (compiled
  extensions, unparseable files);
- degrades honestly: a module that fails to parse contributes no import edges
  (scope can only ever **widen** vs. the pre-fix rule, never narrow);
- cached per project root on a (path, mtime, size) fingerprint, so a develop
  session pays the parse cost once per tree state (~1 s cold / ~0.16 s warm on
  `packaging`; ~2.5 s cold on Apex's own 630-module body).

`covering_test_files` now unions these reachability targets into its matching,
and `impacted_test_files` (the per-move verify gate) inherits the fix.

## Proof

- **Falsifiable tests, red-first**: all 7 semantic tests in
  `tests/test_covering_scope_reachability_eyml.py` FAILED on the pre-fix code
  (child import, transitive, relative transitive, `src/` layout transitive,
  cycle termination, cache invalidation, develop-loop integration), then
  passed after the fix. Anti-balloon guard: an importer-less module still gets
  a tight scope.
- **The real tree**: on the pristine `packaging` 26.2 copy,
  `covering_test_files("src/packaging/licenses/__init__.py")` now includes
  `tests/test_licenses.py` — the exact test whose absence produced the fake
  green.
- **Blind-spot pin flipped**: the years-pinned re-export miss is now asserted
  as *covered* (`test_covering_selection_resolves_reexport_indirection`).
  The `exec`-string import blind spot remains pinned as an honest miss — a
  dotted name inside a string is invisible to any deterministic AST scan.
- **Scope-size honesty on Apex itself** (old → new covering test files):
  hub modules widen a lot (`cross_file_rename` 110 → 737,
  `mutation_tester` 59 → 425) because they really are imported everywhere;
  leaf modules stay tight (`test_impact` 53 → 53). Correctness first; the
  full suite remains the backstop gate.

## What this unlocks

Per-move verification stops trusting an import net with known holes — the
"verified" stamp now means the tests that *actually execute* the change ran.
This is the trust rail both product pitches stand on ("zero-token mechanical
work", "trust rails for LLM coding agents"), and it is what lets Apex's own
develop loop verify moves on Apex's own body instead of marking them no-suite.
