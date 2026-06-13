"""Self-registering objective: dict-comprehension.

The transform lives in :mod:`app.execution.dict_comprehension`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective dict-comprehension` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.dict_comprehension import plan_dict_comprehension

    return [rel for rel, _src in _own_modules(project_root)
            if plan_dict_comprehension(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still match dict-comprehension (lower is better)."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.dict_comprehension import plan_dict_comprehension

    return [Move(
        operator="dict_comprehension",
        target=f"{rel}:dict-comprehension",
        description=f"apply dict-comprehension in {rel}",
        build_plan=lambda r=rel: plan_dict_comprehension(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="dict-comprehension", fitness=fitness, moves=moves))
