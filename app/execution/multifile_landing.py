"""Multi-file atomic landing — the first COMPOSED concrete contribution.

The canonical coordinated change a budget-limited team writes by hand: implement
a tested stub in module A AND wire its new public export in the package
``__init__.py`` — as ONE verified unit. Today Apex lands each half separately
(``implement-stub`` on A, ``wire-exports`` on the package); this composes them so
the filled stub and the wired ``__init__.py`` land TOGETHER, gated once, and roll
back together byte-for-byte if the combined change regresses.

:func:`plan_implement_and_wire` builds the two single-file plans with the
EXISTING objective planners (``plan_implement_stub`` / ``plan_wire_exports``) and
merges them through :func:`compose_plans`. :func:`multifile_moves` offers one
:class:`Move` per (stub-module, owning-package) pair for an explicit, opt-in
demonstration path.

This is a COMPOSITION PRIMITIVE, not a develop objective: it does NOT
``register()`` (so it never enters ``available_objectives()`` — no Facet-parity
obligation, no soundness-manifest entry) and NEVER calls :func:`apply_rename`
(the composed plan flows through the one legal gated-writer call site in
``objective_compiler``, exactly like every single-file plan). Deterministic,
stdlib-only, zero-token.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.compose_plans import compose_plans
from app.execution.cross_file_rename import RenamePlan
from app.execution.objectives.implement_stub import plan_implement_stub
from app.execution.objectives.wire_exports import plan_wire_exports


def _owning_package_init(module_rel: str) -> str:
    """The ``__init__.py`` of the package that OWNS ``module_rel``.

    A module ``app/pkg/calc.py`` is re-exported by its own directory's package
    ``app/pkg/__init__.py`` — the package whose public surface ``wire-exports``
    composes the module's symbols into. Pure posix path join, no filesystem
    touch, deterministic."""
    parent = Path(module_rel.replace("\\", "/")).parent
    return (parent / "__init__.py").as_posix()


def plan_implement_and_wire(
    project_root: str | Path, module_rel: str,
) -> RenamePlan:
    """Build the composed implement-the-stub-AND-wire-its-export plan, or a
    refusal that lands nothing.

    Builds ``plan_implement_stub(module_rel)`` and ``plan_wire_exports`` for the
    module's owning package ``__init__.py``, then merges them with
    :func:`compose_plans`. Each sub-planner runs its own refusals/oracles FIRST
    (implement-stub's never-fake-green template gate; wire-exports' import
    oracle), so a refused half can never enter the union — and a file overlap or
    an empty half makes the composition refuse honestly. The merged plan is
    gated once and rolled back as a unit by the existing engine."""
    root = Path(project_root)
    stub = plan_implement_stub(root, module_rel)
    wire = plan_wire_exports(root, _owning_package_init(module_rel))
    return compose_plans(stub, wire)


def _stub_modules(project_root: str | Path) -> list[str]:
    """Own modules that hold at least one fillable stub — reusing implement-stub's
    own cheap in-process scan so the pairing offers exactly the modules that
    objective would. Sorted/deterministic (the scan returns a sorted list)."""
    from app.execution.objectives.implement_stub import _modules

    return list(_modules(project_root))


def multifile_moves(project_root: str | Path) -> list:
    """One :class:`Move` per (stub-module, owning-package) pair whose composed
    plan would land something.

    Pairs every fillable-stub module with its package ``__init__.py`` and offers
    the composed implement-and-wire plan. ``scope_verify`` is requested on the
    Move's gate via ``compile_objective(..., scope_verify=True)`` by the caller
    (both halves are audited red-baseline objectives). A pair whose composition
    refuses (no wireable export, file overlap, …) simply no-ops at apply, exactly
    like a single-file objective whose plan is empty. Deterministic: modules are
    taken in the cheap scan's fixed sorted order."""
    from app.engine.objective_compiler import Move

    out: list = []
    for rel in _stub_modules(project_root):
        out.append(Move(
            operator="implement_and_wire",
            target=f"{rel}:implement-and-wire",
            description=f"implement a tested stub in {rel} AND wire its export",
            build_plan=lambda r=rel: plan_implement_and_wire(project_root, r),
        ))
    return out
