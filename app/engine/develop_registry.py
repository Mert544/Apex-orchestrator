"""Develop-objective registry — let a new ability register ITSELF.

Until now, teaching the Objective-Compiler a new move meant editing two hub
files by hand (``objective_compiler._OBJECTIVES`` and, to group it, the fractal
tree). That hand-wiring is the integration bottleneck: two abilities can't be
added in parallel without colliding on those hubs.

This registry removes the bottleneck. A develop objective is just a name plus
two pure functions — a *fitness* (how much fixable debt remains) and a *moves*
generator (the candidate transforms). Any module under
``app/execution/objectives/`` that calls :func:`register` (or uses the
:func:`objective` decorator) becomes a first-class objective the moment it is
discovered — no hub edit, so two such modules never conflict. An ability now
ships as ONE self-contained file: its transform, its registration, its tests.

Discovery is deterministic (modules imported in sorted order) and idempotent
(import-once), and the registry never overrides a built-in objective of the same
name — built-ins win, discovered ones extend. Stdlib-only, no LLM.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.objective_compiler import Move

__all__ = [
    "ObjectiveSpec", "register", "objective", "discover",
    "registered_specs", "clear_registry",
]

# The package every self-registering objective lives in. Dropping a module here
# that calls register() (at import) is all it takes to add an objective.
_OBJECTIVES_PACKAGE = "app.execution.objectives"


@dataclass(frozen=True)
class ObjectiveSpec:
    """One develop objective: a name and the two pure functions that drive it.

    ``fitness(project_root) -> float`` is the count of fixable items remaining
    (lower is better; 0 means the objective is met). ``moves(project_root) ->
    list[Move]`` yields the candidate transforms the compiler may compose.
    """
    name: str
    fitness: Callable[[str | Path], float]
    moves: Callable[[str | Path], "list[Move]"]


_REGISTRY: dict[str, ObjectiveSpec] = {}
_DISCOVERED = False


def register(spec: ObjectiveSpec) -> ObjectiveSpec:
    """Register (or replace) an objective by name. Returns the spec, so it can
    be used as ``SPEC = register(ObjectiveSpec(...))``. Re-registering the same
    name (e.g. a module re-imported under test) is harmless — last write wins."""
    _REGISTRY[spec.name] = spec
    return spec


def objective(name: str, fitness: Callable[[str | Path], float]):
    """Decorator form: register the decorated *moves* function as objective
    ``name`` with the given ``fitness``. Returns the function unchanged.

        @objective("collapse-foo", _foo_fitness)
        def _foo_moves(project_root): ...
    """
    def _wrap(moves: Callable[[str | Path], "list[Move]"]):
        register(ObjectiveSpec(name=name, fitness=fitness, moves=moves))
        return moves
    return _wrap


def discover(*, force: bool = False) -> dict[str, ObjectiveSpec]:
    """Import every module under ``app/execution/objectives/`` so its
    registration fires, then return the registry. Idempotent: the import sweep
    runs once (use ``force=True`` to re-sweep). Modules are imported in sorted
    name order, so discovery is deterministic."""
    global _DISCOVERED
    if _DISCOVERED and not force:
        return _REGISTRY
    try:
        package = importlib.import_module(_OBJECTIVES_PACKAGE)
    except ModuleNotFoundError:
        _DISCOVERED = True
        return _REGISTRY
    names = sorted(
        info.name for info in pkgutil.iter_modules(package.__path__)
        if not info.name.startswith("_")
    )
    for mod in names:
        importlib.import_module(f"{_OBJECTIVES_PACKAGE}.{mod}")
    _DISCOVERED = True
    return _REGISTRY


def registered_specs() -> dict[str, ObjectiveSpec]:
    """The discovered objective specs (runs discovery on first call)."""
    discover()
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Drop all registrations and reset discovery — for tests only."""
    global _DISCOVERED
    _REGISTRY.clear()
    _DISCOVERED = False
