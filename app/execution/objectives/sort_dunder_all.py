"""Self-registering objective: sort-dunder-all.

Sort + de-duplicate an existing module-level ``__all__ = [...]`` (or ``(...)``) of
STRING LITERALS into canonical lexicographic order — the readability tidy a careful
author keeps by hand. Behaviour-IDENTICAL: the ORDER of ``__all__`` never affects
``from m import *`` (only which names are exported), so reordering and dropping an
accidental duplicate changes nothing observable. Where a linter only flags an
unsorted ``__all__``, Apex rewrites it, deterministically and for free.

The detection + minimal rewrite live in :mod:`app.execution.sort_dunder_all`
(``sort_module_all``); this module only names it as a develop objective and
registers itself. Standard single-file shape, so it reuses ``plan_source_rewrite``.

DISTINCT from wire-module-exports (which CREATES an ``__all__`` on a module that has
NONE): this one SORTS an ``__all__`` that already exists. The two are mutually
exclusive on any module — a module has either zero ``__all__`` (wire-module-exports
may act) or one (sort-dunder-all may act) — so they never conflict, and because
wire-module-exports emits an already-sorted ``__all__``, sort-dunder-all is a
byte-identical no-op on a freshly-wired one (they compose to a fixpoint).

REFUSES (a no-op) unless ``__all__`` is a PLAIN literal list/tuple of string
literals: a computed ``__all__`` (a name, ``_BASE + [...]``, ``list(...)``, a
comprehension), an ``__all__ += [...]`` / ``__all__.append(...)`` / conditional
re-binding, a non-string element, more than one ``__all__``, or unparseable source
→ REFUSE. Idempotent (an already-canonical ``__all__`` is a byte-identical no-op).
Deterministic (pure AST walk + line splice, no clock/random), stdlib-only,
zero-token.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.sort_dunder_all import sort_module_all


def plan_sort_dunder_all(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the sort-dunder-all plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture, read, run ``sort_module_all``, record the one in-place rewrite
    with its original so the verified-apply engine can roll it back). An empty plan
    means nothing to do here — no ``__all__``, a computed/dynamic ``__all__``, a
    non-string element, an already-canonical list, or unparseable source — a no-op,
    not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "sort_dunder_all", sort_module_all)


register_module_objective(
    "sort-dunder-all", plan_sort_dunder_all,
    operator="sort_dunder_all",
    description="sort and de-duplicate __all__ in {rel}",
)
