"""Self-registering objective: remove-redundant-else.

Drop an ``else`` whose ``if`` branch already exits (its body ends in a
terminal), dedenting the else-body so it stands as siblings after the ``if``.
The transform lives in :mod:`app.execution.redundant_else`; this module only
names it as a develop objective and registers itself with the develop registry.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.redundant_else import plan_remove_redundant_else

    return [rel for rel, _src in _own_modules(project_root)
            if plan_remove_redundant_else(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a redundant else to remove."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.redundant_else import plan_remove_redundant_else

    return [Move(
        operator="remove_redundant_else", target=f"{rel}:redundant-else",
        description=f"remove redundant else after a terminal in {rel}",
        build_plan=lambda r=rel: plan_remove_redundant_else(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="remove-redundant-else", fitness=fitness,
                       moves=moves))
