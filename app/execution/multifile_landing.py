"""Multi-file atomic landing — the first COMPOSED concrete contribution.

The canonical coordinated change a budget-limited team writes by hand: implement
a tested stub in module A AND wire its new public export in the package
``__init__.py`` — as ONE verified unit. Today Apex lands each half separately
(``implement-stub`` on A, ``wire-exports`` on the package); this composes them so
the filled stub and the wired ``__init__.py`` land TOGETHER, gated once, and roll
back together byte-for-byte if the combined change regresses.

:func:`plan_module_chain` is the GENERAL builder: given a MODULE and a list of
objective names, it asks each objective's planner for the ONE single-file plan it
contributes for that module (each objective owns a DISTINCT file relative to the
module — ``implement-stub`` the module itself, ``wire-exports`` its owning package
``__init__.py``, …), then folds those plans into ONE multi-file plan with
:func:`compose_chain`. :func:`plan_implement_and_wire` is a thin call into it over
the canonical ``implement-stub`` + ``wire-exports`` chain. :func:`multifile_moves`
offers one :class:`Move` per (stub-module, owning-package) pair for an explicit,
opt-in demonstration path.

This is a COMPOSITION PRIMITIVE, not a develop objective: it does NOT
``register()`` (so it never enters ``available_objectives()`` — no Facet-parity
obligation, no soundness-manifest entry) and NEVER calls :func:`apply_rename`
(the composed plan flows through the one legal gated-writer call site in
``objective_compiler``, exactly like every single-file plan). Deterministic,
stdlib-only, zero-token.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.execution.compose_plans import compose_chain
from app.execution.cross_file_rename import RenamePlan
from app.execution.objectives.implement_stub import plan_implement_stub
from app.execution.objectives.wire_exports import plan_wire_exports

# The default per-module chain: implement the module's tested stub AND wire its
# export. Kept as a module constant so :func:`plan_implement_and_wire` and the
# demonstration moves share one source of truth for the canonical pairing.
_IMPLEMENT_AND_WIRE: tuple[str, ...] = ("implement-stub", "wire-exports")

# Objective name -> the single-file plan it contributes FOR a given module. Each
# builder maps ``(project_root, module_rel)`` to that objective's plan for the
# file it owns relative to the module: ``implement-stub`` fills the module itself;
# ``wire-exports`` surfaces the module's symbols in its OWNING package's
# ``__init__.py``. This is the ONLY place a per-module chain widens — add an
# objective here (paired with the file it touches for the module) and any chain
# naming it composes automatically. Every builder is a thin call into the EXISTING
# objective planner — no new planning, no writes.
_MODULE_PLAN_BUILDERS: dict[str, Callable[[Path, str], RenamePlan]] = {
    "implement-stub": lambda root, rel: plan_implement_stub(root, rel),
    "wire-exports": lambda root, rel: plan_wire_exports(
        root, _owning_package_init(rel)),
}


def _owning_package_init(module_rel: str) -> str:
    """The ``__init__.py`` of the package that OWNS ``module_rel``.

    A module ``app/pkg/calc.py`` is re-exported by its own directory's package
    ``app/pkg/__init__.py`` — the package whose public surface ``wire-exports``
    composes the module's symbols into. Pure posix path join, no filesystem
    touch, deterministic."""
    parent = Path(module_rel.replace("\\", "/")).parent
    return (parent / "__init__.py").as_posix()


def plan_module_chain(
    project_root: str | Path, module_rel: str,
    objectives: tuple[str, ...] | list[str] = _IMPLEMENT_AND_WIRE,
) -> RenamePlan:
    """Build ONE composed plan from a MODULE's applicable single-file objective
    plans, or a refusal that lands nothing.

    For each objective NAME in ``objectives`` (in order), asks
    :data:`_MODULE_PLAN_BUILDERS` for the ONE single-file plan that objective
    contributes for ``module_rel`` — the identical EXISTING objective planner
    (``plan_implement_stub`` on the module, ``plan_wire_exports`` on its owning
    package ``__init__.py``, …), each of which runs its OWN refusals/oracles first
    (implement-stub's never-fake-green template gate, wire-exports' import oracle).
    The collected plans are folded into one multi-file plan with
    :func:`compose_chain`.

    Refuses (lands nothing) exactly as :func:`compose_chain` does: when fewer than
    two objectives yield a plan to compose, when any collected plan is blocked or
    empty (a refused half can never enter the union), or when any two plans touch
    the SAME file. An UNKNOWN objective name (one with no per-module builder) is
    refused UP FRONT — naming the objective — so the caller learns exactly which
    name is not chainable rather than getting the fold's generic refusal. The
    merged plan is gated once and rolled back as a unit by the existing engine —
    no new gate, no writes here. Deterministic: the objectives drive the fold in
    the given order."""
    root = Path(project_root)
    unknown = [name for name in objectives if name not in _MODULE_PLAN_BUILDERS]
    if unknown:
        # Fail fast with the SPECIFIC name(s): the fold would otherwise fold the
        # blocked sub-plan into compose_plans' generic "a sub-plan already refused"
        # message, hiding which objective is not chainable. Honest disclosure.
        return _chain_refusal(
            f"objective(s) {sorted(unknown)} are not per-module chain builders")
    plans = [_MODULE_PLAN_BUILDERS[name](root, module_rel) for name in objectives]
    return compose_chain(plans)


def _chain_refusal(reason: str) -> RenamePlan:
    """An empty per-module chain plan that lands NOTHING — ``.blockers`` set (so
    ``.ok`` is False), mirroring :func:`compose_plans`' refusal shape."""
    plan = RenamePlan(old="compose", new="compose")
    plan.blockers.append(reason)
    return plan


def _module_objective_plan(root: Path, module_rel: str, objective: str) -> RenamePlan:
    """The single-file plan ``objective`` contributes for ``module_rel``, or an
    empty plan carrying an honest reason when the objective is not chainable.

    Looks the objective up in :data:`_MODULE_PLAN_BUILDERS` and calls the EXISTING
    planner. An objective absent from the registry yields an empty plan whose
    blocker names it (so a caller that composes it directly still refuses honestly,
    never a silent drop). :func:`plan_module_chain` refuses on such a name up front;
    this helper is the single-objective dispatch used to build one leaf's plan.
    Pure plan construction — no writes, no gate."""
    builder = _MODULE_PLAN_BUILDERS.get(objective)
    if builder is None:
        return _chain_refusal(
            f"objective '{objective}' is not a per-module chain builder")
    return builder(root, module_rel)


def plan_implement_and_wire(
    project_root: str | Path, module_rel: str,
) -> RenamePlan:
    """Build the composed implement-the-stub-AND-wire-its-export plan, or a
    refusal that lands nothing.

    A thin call into :func:`plan_module_chain` over the canonical
    ``implement-stub`` + ``wire-exports`` chain: it builds
    ``plan_implement_stub(module_rel)`` and ``plan_wire_exports`` for the module's
    owning package ``__init__.py``, then merges them. Each sub-planner runs its own
    refusals/oracles FIRST (implement-stub's never-fake-green template gate;
    wire-exports' import oracle), so a refused half can never enter the union — and
    a file overlap or an empty half makes the composition refuse honestly. The
    merged plan is gated once and rolled back as a unit by the existing engine."""
    return plan_module_chain(project_root, module_rel, _IMPLEMENT_AND_WIRE)


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
