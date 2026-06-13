"""Self-registering objective: percent-to-fstring.

The transform lives in :mod:`app.execution.percent_to_fstring`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective percent-to-fstring` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.percent_to_fstring import plan_percent_to_fstring

    return [rel for rel, _src in _own_modules(project_root)
            if plan_percent_to_fstring(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a convertible ``%``-format."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.percent_to_fstring import plan_percent_to_fstring

    return [Move(
        operator="percent_to_fstring",
        target=f"{rel}:percent-to-fstring",
        description=f"convert '%s'-formatting to f-strings in {rel}",
        build_plan=lambda r=rel: plan_percent_to_fstring(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="percent-to-fstring", fitness=fitness, moves=moves))
