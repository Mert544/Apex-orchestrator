"""Self-registering objective: simplify-ternary-bool.

The transform lives in :mod:`app.execution.simplify_ternary_bool`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective simplify-ternary-bool` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.simplify_ternary_bool import plan_simplify_ternary_bool

    return [rel for rel, _src in _own_modules(project_root)
            if plan_simplify_ternary_bool(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still match simplify-ternary-bool (lower is better)."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.simplify_ternary_bool import plan_simplify_ternary_bool

    return [Move(
        operator="simplify_ternary_bool",
        target=f"{rel}:simplify-ternary-bool",
        description=f"apply simplify-ternary-bool in {rel}",
        build_plan=lambda r=rel: plan_simplify_ternary_bool(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="simplify-ternary-bool", fitness=fitness, moves=moves))
