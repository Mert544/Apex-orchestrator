"""Self-registering objective: fstring-convert.

Rewrite a simple ``"...{}...".format(args)`` call into the equivalent f-string.
The transform lives in :mod:`app.execution.fstring_convert`; this module only
names it as a develop objective and registers itself with the develop registry.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _modules(project_root: str | Path) -> list[str]:
    from app.engine.objective_compiler import _own_modules
    from app.execution.fstring_convert import plan_fstring_convert

    return [rel for rel, _src in _own_modules(project_root)
            if plan_fstring_convert(project_root, rel).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a convertible .format() call."""
    return float(len(_modules(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move
    from app.execution.fstring_convert import plan_fstring_convert

    return [Move(
        operator="fstring_convert", target=f"{rel}:fstring-convert",
        description=f"convert .format() to f-strings in {rel}",
        build_plan=lambda r=rel: plan_fstring_convert(project_root, r),
    ) for rel in _modules(project_root)]


register(ObjectiveSpec(name="fstring-convert", fitness=fitness, moves=moves))
