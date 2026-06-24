"""Self-registering objective: add-from-future-annotations.

Land ``from __future__ import annotations`` (PEP 563) on a project's own module
that USES type annotations but does not yet defer their evaluation — the one-line
modernization a student or team writes by hand on every new typed file. Where a
linter only FLAGS the missing import, this WRITES it: a fresh ``from __future__
import annotations`` after the docstring, or an existing ``from __future__ import
...`` widened in place to add ``annotations``. Behaviour-preserving (annotations
become lazy strings), value-identical, no guess.

The detection + minimal rewrite live in
:mod:`app.execution.future_annotations` (``add_future_annotations``); this module
only names it as a develop objective and registers itself with the develop
registry. Standard single-file shape, so it reuses ``plan_source_rewrite`` — the
same suite-gated, auto-rollback develop loop every objective uses, and the plan
layer refuses test/fixture files. The transform refuses (a no-op) a module with no
annotations, one that already imports ``annotations``, or unparseable source.

The single runtime risk — a module that EAGERLY resolves its own annotations at
import time via ``typing.get_type_hints()`` (lazy annotations can then ``NameError``
on a forward-only name) — is caught by the full-suite gate + byte-for-byte
rollback. Deterministic, stdlib-only, zero-token, idempotent (a second run sees the
import it landed and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.future_annotations import add_future_annotations
from app.execution.objectives._base import register_module_objective


def plan_from_future_annotations(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the add-from-future-annotations plan for one module, or an honest
    no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture, read, run ``add_future_annotations``, record the one in-place
    rewrite with its original so the verified-apply engine can roll it back). An
    empty plan means nothing to do here — the module uses no annotations, already
    defers them, or does not parse — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "add_from_future_annotations",
        add_future_annotations)


register_module_objective(
    "add-from-future-annotations", plan_from_future_annotations,
    operator="add_from_future_annotations",
    description="add `from __future__ import annotations` to {rel}",
)
