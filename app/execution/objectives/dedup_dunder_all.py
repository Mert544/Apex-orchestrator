"""Self-registering objective: dedup-dunder-all.

De-duplicate an existing module-level ``__all__ = [...]`` (or ``(...)``) of STRING
LITERALS, PRESERVING first-appearance order — the minimal, order-faithful fix for a
copy-paste duplicate export. Behaviour-IDENTICAL: the CONTENTS of ``__all__`` are a
membership SET (``from m import *`` consults only which names appear, never how many
times), so removing a repeat changes nothing observable. Where a linter only flags a
duplicated ``__all__`` entry, Apex rewrites it, deterministically and for free.

The detection + minimal rewrite live in :mod:`app.execution.dedup_dunder_all`
(``dedup_module_all``); this module only names it as a develop objective and
registers itself. Standard single-file shape, so it reuses ``plan_source_rewrite``.

DISTINCT from sort-dunder-all (which SORTS ``__all__`` into lexicographic order, and
de-dupes only as a side effect): this one keeps the author's ORIGINAL order and
removes ONLY the duplicates — a no-op on a duplicate-free list whatever its order, so
it never reorders a deliberately-grouped ``__all__`` a sort would churn. The two are
separate, opt-in objectives; the engine picks at most one per module per wave.

REFUSES (a no-op) unless ``__all__`` is a PLAIN literal list/tuple of string literals
WITH a real duplicate and NO comment in its statement span: a computed ``__all__`` (a
name, ``_BASE + [...]``, ``list(...)``, a comprehension), an ``__all__ += [...]`` /
``__all__.append(...)`` / conditional re-binding, a non-string / starred element, more
than one ``__all__``, a duplicate-free list, a commented span (removing a dup line
would orphan the comment — comment-loss), or unparseable source → REFUSE. Idempotent
(the de-duplicated ``__all__`` has no remaining duplicate, so a second run is a
byte-identical no-op). Deterministic (pure AST + ``tokenize`` scan + line splice, no
clock/random), stdlib-only, zero-token.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.dedup_dunder_all import dedup_module_all
from app.execution.objectives._base import register_module_objective


def plan_dedup_dunder_all(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the dedup-dunder-all plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture/non-library, read, run ``dedup_module_all``, record the one in-place
    rewrite with its original so the verified-apply engine can roll it back). An empty
    plan means nothing to do here — no ``__all__``, a computed/dynamic ``__all__``, a
    non-string element, a duplicate-free list, a commented span, or unparseable source
    — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "dedup_dunder_all", dedup_module_all)


register_module_objective(
    "dedup-dunder-all", plan_dedup_dunder_all,
    operator="dedup_dunder_all",
    description="de-duplicate __all__ in {rel} preserving first-appearance order",
)
