"""Self-registering objective: fix-not-in-is.

The transform lives in :mod:`app.execution.fix_not_in_is`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective fix-not-in-is` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.fix_not_in_is import plan_fix_not_in_is

    return [rel for rel, _src in _own_modules(project_root)
            if plan_fix_not_in_is(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still match fix-not-in-is (lower is better)."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.fix_not_in_is import plan_fix_not_in_is

    return [Move(
        operator="fix_not_in_is",
        target=f"{rel}:fix-not-in-is",
        description=f"apply fix-not-in-is in {rel}",
        build_plan=lambda r=rel: plan_fix_not_in_is(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="fix-not-in-is", fitness=fitness, moves=moves))
