"""Self-registering objective: combine-nested-with.

Collapse ``with A:\\n    with B:`` into ``with A, B:``. The transform lives in
:mod:`app.execution.nested_with`; this module only names it as a develop
objective and registers itself with the develop registry.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.nested_with import plan_combine_nested_with

    return [rel for rel, _src in _own_modules(project_root)
            if plan_combine_nested_with(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a collapsible nested ``with``."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.nested_with import plan_combine_nested_with

    return [Move(
        operator="combine_nested_with",
        target=f"{rel}:combine-nested-with",
        description=f"combine nested with-statements in {rel}",
        build_plan=lambda r=rel: plan_combine_nested_with(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="combine-nested-with", fitness=fitness, moves=moves))
