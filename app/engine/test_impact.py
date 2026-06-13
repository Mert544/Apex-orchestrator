"""Impact-scoped test selection — which tests actually exercise a change.

Running the whole suite after every develop move is the safe default, but on a
large project it is far too slow for a per-move gate — so slow that the organism
can't develop its OWN body (each move would pay the full-suite cost). Apex
already knows, deterministically, which test files import a given module
(:func:`covering_test_files`). This maps a set of CHANGED files to the union of
the tests that reach them, so a move can be verified against just those, in
seconds. The full suite stays the backstop gate (run once before a commit).

Deterministic, stdlib-only.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

__all__ = ["impacted_test_files"]


def _is_test_file(rel: str) -> bool:
    name = Path(rel).name
    return name.startswith("test_") and name.endswith(".py")


def impacted_test_files(project_root: str | Path,
                        changed_files: Iterable[str]) -> list[str]:
    """The test files that exercise ``changed_files`` — a deterministic,
    de-duplicated, sorted scope for verifying a single change.

    A changed file that IS a test is included directly (its own change must be
    run). For a changed source module, every test whose imports reach it (via
    :func:`covering_test_files`) is included. The result is empty when nothing
    covers the change — the caller should then fall back to the full suite, since
    an unreferenced change can't be impact-verified."""
    from app.engine.mutation_tester import covering_test_files

    root = Path(project_root)
    impacted: set[str] = set()
    for rel in changed_files:
        rel = Path(rel).as_posix()
        if _is_test_file(rel):
            impacted.add(rel)
        else:
            impacted.update(covering_test_files(root, rel))
    return sorted(impacted)
