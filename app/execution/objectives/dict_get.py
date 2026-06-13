"""Self-registering objective: simplify-dict-get.

Rewrite ``x[k] if k in x else d`` into ``x.get(k, d)``. The transform lives in
:mod:`app.execution.dict_get`; this module only names it as a develop objective
and registers itself with the develop registry.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.dict_get import plan_simplify_dict_get

    return [rel for rel, _src in _own_modules(project_root)
            if plan_simplify_dict_get(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a dict-get ternary to simplify."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.dict_get import plan_simplify_dict_get

    return [Move(
        operator="simplify_dict_get", target=f"{rel}:simplify-dict-get",
        description=f"simplify dict-get ternaries in {rel}",
        build_plan=lambda r=rel: plan_simplify_dict_get(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="simplify-dict-get", fitness=fitness, moves=moves))
