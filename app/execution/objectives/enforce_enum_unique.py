"""Self-registering objective: enforce-enum-unique.

Land ``@enum.unique`` on a project's own ``Enum`` subclass whose members are
PROVEN to all carry distinct simple-literal values — the type-and-runtime guard a
careful author writes by hand to lock the invariant against a future
duplicate-value alias. ``@enum.unique`` is a PURE no-op TODAY on an
already-distinct enum (it raises ``ValueError`` ONLY on a duplicate value, of which
the soundness proof guarantees there are none), so the change is behaviour-
preserving BY CONSTRUCTION; the only honesty risk — a false enforce that would
raise at import — is closed STATICALLY by refusing unless EVERY member value is a
distinct simple literal (an ``auto()``, a computed/non-literal value, an
``==``-colliding pair, an already-``@unique`` enum, or an enum with no provable
spelling of ``enum.unique`` → REFUSE, an honest no-op). Where a linter only FLAGS
the opportunity, Apex WRITES it, deterministically and for free.

The detection + minimal rewrite live in :mod:`app.execution.enum_unique`
(``add_enum_unique_decorator``); this module only names it as a develop objective
and registers itself. Standard single-file shape — no whole-project scan is needed
(the distinctness proof is purely intra-module, UNLIKE the @final family whose
soundness needs a project-wide subclass scan) — so it reuses ``plan_source_rewrite``
directly. The transform refuses (a no-op) a module with no uniqueable enum: not an
``Enum`` subclass, already ``@unique``, a non-literal / ``auto()`` / computed /
``==``-colliding member value, an empty enum, an unmodelled class-body binder, the
name ``unique`` not provably ``enum.unique``, or unparseable source.

``enum.unique`` exists since Python 3.4, so this lands on the 3.10 floor with NO
version gate. Deterministic (pure AST walk + line splice, no clock/random),
stdlib-only, zero-token, idempotent (a second run sees the ``@unique`` it landed
and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.enum_unique import add_enum_unique_decorator
from app.execution.objectives._base import register_module_objective


def plan_enforce_enum_unique(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the enforce-enum-unique plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture, read, run ``add_enum_unique_decorator``, record the one in-place
    rewrite with its original so the verified-apply engine can roll it back). An
    empty plan means nothing to do here — no uniqueable enum, or the module does
    not parse — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "enforce_enum_unique",
        add_enum_unique_decorator)


register_module_objective(
    "enforce-enum-unique", plan_enforce_enum_unique,
    operator="enforce_enum_unique",
    description="add @enum.unique to a proven-distinct Enum in {rel}",
)
