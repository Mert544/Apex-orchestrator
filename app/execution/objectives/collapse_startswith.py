"""Self-registering objective: collapse-startswith.

Collapse ``x.startswith(a) or x.startswith(b)`` into ``x.startswith((a, b))``
(and the same for ``.endswith``). The transform lives in
:mod:`app.execution.startswith_tuple`; this module registers it as an objective.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.startswith_tuple import plan_collapse_startswith

    return [rel for rel, _src in _own_modules(project_root)
            if plan_collapse_startswith(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a collapsible startswith chain."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.startswith_tuple import plan_collapse_startswith

    return [Move(
        operator="collapse_startswith", target=f"{rel}:collapse-startswith",
        description=f"collapse startswith/endswith or-chains in {rel}",
        build_plan=lambda r=rel: plan_collapse_startswith(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="collapse-startswith", fitness=fitness, moves=moves))
