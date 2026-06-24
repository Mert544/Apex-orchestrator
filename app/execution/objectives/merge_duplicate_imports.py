"""Self-registering objective: merge-duplicate-imports.

Collapse MULTIPLE top-level ``from <same-module> import ...`` statements (same
module, same relative level) into ONE, preserving every imported alias in
first-appearance order and de-duplicating exact repeats. Where a linter only FLAGS
repeated import lines, this WRITES the single merged statement. PROVABLY
behaviour-preserving: the multiset of ``(module, level, name, asname)`` bindings is
unchanged — only the line count drops (importing the same module twice is a no-op in
CPython, so the merge cannot change an import side effect either).

The detection + minimal rewrite live in :mod:`app.execution.duplicate_imports`
(``merge_duplicate_imports``); this module only names it as a develop objective and
registers itself with the develop registry. Standard single-file shape, so it reuses
``plan_source_rewrite`` — the same suite-gated, auto-rollback develop loop every
objective uses, and the plan layer refuses test/fixture files. The transform is an
honest no-op (returns ``None``) on a module with no duplicate group, and REFUSES
(leaving the whole module untouched) the moment a merge could change meaning or lose
information: a ``from __future__ import`` (order/placement-sensitive), a ``from x
import *``, a duplicate line carrying a ``# noqa``/``# type:``/trailing comment that
would be lost, an INCOMPATIBLE alias (the same local bound from two different
``name``/``asname`` pairs), an import guarded by a different ``if``/``try`` block, or
imports separated by intervening execution-relevant code.

This is a TIDY objective (it merges EXISTING import lines; it lands no code that did
not exist), classed as such in the North Star manifest so the denetçi's
concrete-ratio stays honest. Deterministic, stdlib-only, zero-token, idempotent (a
second run sees the merged statement and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.duplicate_imports import merge_duplicate_imports
from app.execution.objectives._base import register_module_objective


def plan_merge_duplicate_imports(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the merge-duplicate-imports plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture, read, run ``merge_duplicate_imports``, record the one in-place
    rewrite with its original so the verified-apply engine can roll it back). An
    empty plan means nothing to do here — the module has no duplicate ``from``-import
    group, a merge would change meaning (refused), or it does not parse — a no-op,
    not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "merge_duplicate_imports",
        merge_duplicate_imports)


register_module_objective(
    "merge-duplicate-imports", plan_merge_duplicate_imports,
    operator="merge_duplicate_imports",
    description="merge duplicate from-imports in {rel}",
)
