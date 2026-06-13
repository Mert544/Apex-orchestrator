"""Self-registering objective: set-literal.

The transform lives in :mod:`app.execution.set_literal`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective set-literal` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.set_literal import plan_set_literal

    return [rel for rel, _src in _own_modules(project_root)
            if plan_set_literal(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still match set-literal (lower is better)."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.set_literal import plan_set_literal

    return [Move(
        operator="set_literal",
        target=f"{rel}:set-literal",
        description=f"apply set-literal in {rel}",
        build_plan=lambda r=rel: plan_set_literal(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="set-literal", fitness=fitness, moves=moves))
