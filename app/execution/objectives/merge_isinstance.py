"""Self-registering objective: merge-isinstance.

Collapse ``isinstance(x, A) or isinstance(x, B)`` into ``isinstance(x, (A, B))``.
The transform lives in :mod:`app.execution.merge_isinstance`; this module only
names it as a develop objective and registers itself with the develop registry.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.merge_isinstance import plan_merge_isinstance

    return [rel for rel, _src in _own_modules(project_root)
            if plan_merge_isinstance(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a mergeable isinstance chain."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.merge_isinstance import plan_merge_isinstance

    return [Move(
        operator="merge_isinstance", target=f"{rel}:merge-isinstance",
        description=f"merge isinstance or-chains in {rel}",
        build_plan=lambda r=rel: plan_merge_isinstance(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="merge-isinstance", fitness=fitness, moves=moves))
