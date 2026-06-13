"""Shared helper for STANDARD self-registering develop objectives.

Almost every objective under ``app/execution/objectives/`` is the *same shape*:
run a single ``plan_<x>(project_root, module_rel)`` transform over every one of
the project's own modules, count the modules it would change (the fitness), and
offer one :class:`~app.engine.objective_compiler.Move` per such module. Before
this helper, each spec hand-copied that identical ``_modules`` / ``fitness`` /
``moves`` trio — 30-odd duplicated lines per ability.

:func:`register_module_objective` collapses that trio into one call, so a
standard spec is ~3 lines: import the transform, import this helper, register.
Behaviour is byte-for-byte what the hand-written trio produced (same module
selection, same fitness, same ``operator``/``target``/``description`` strings),
so existing objectives are unchanged.

The leading underscore in this module's name matters: the registry's
:func:`~app.engine.develop_registry.discover` skips modules starting with ``_``,
so this is a *library* for the specs, never an auto-discovered objective itself.
Unlike the registry, this module may freely import ``objective_compiler`` (the
specs already do — no cycle, since ``objective_compiler`` imports the registry,
not these spec modules). The compiler imports are kept lazy (inside the closures)
exactly as the hand-written specs did them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def register_module_objective(
    name: str,
    plan_fn: Callable[[str | Path, str], object],
    *,
    operator: str,
    description: str,
    target_suffix: str | None = None,
) -> ObjectiveSpec:
    """Register a standard 'run ``plan_fn`` over every own module' objective.

    ``_modules`` = own modules where ``plan_fn(root, rel).new_contents`` is
    non-empty; ``fitness`` = ``len(_modules)``; ``moves`` = one ``Move`` per
    module. ``target_suffix`` defaults to ``name``. ``description`` is a template
    that receives the module path as ``{rel}``. Returns the registered
    :class:`ObjectiveSpec`.
    """
    suffix = target_suffix or name

    def _modules(project_root: str | Path) -> list[str]:
        from app.engine.objective_compiler import _own_modules

        return [rel for rel, _src in _own_modules(project_root)
                if plan_fn(project_root, rel).new_contents]

    def fitness(project_root: str | Path) -> float:
        """Fitness = how many own modules ``plan_fn`` would still change."""
        return float(len(_modules(project_root)))

    def moves(project_root: str | Path) -> list:
        from app.engine.objective_compiler import Move

        return [Move(
            operator=operator,
            target=f"{rel}:{suffix}",
            description=description.format(rel=rel),
            build_plan=lambda r=rel: plan_fn(project_root, r),
        ) for rel in _modules(project_root)]

    return register(ObjectiveSpec(name=name, fitness=fitness, moves=moves))
