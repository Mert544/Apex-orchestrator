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

from collections.abc import Callable
from dataclasses import dataclass
import importlib
from pathlib import Path
import pkgutil

# NOTE: deliberately NO import of app.engine.objective_compiler here — not even
# under TYPE_CHECKING. objective_compiler imports this registry (to merge the
# discovered specs), so importing it back — even for a type name — forms a
# static import cycle that the architecture grade penalises. A `Move` is a
# plain dataclass; the registry only stores and forwards the moves callable, so
# the list element type stays unannotated. The registry has zero dependency on
# the compiler, which is exactly the decoupling that lets abilities self-register.

__all__ = [
    "ObjectiveSpec", "register", "objective", "discover",
    "registered_specs", "clear_registry", "expensive_names",
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
    moves: Callable[[str | Path], list]  # list[Move]; Move left unannotated to avoid an import cycle
    # A heavyweight objective whose fitness scan is slow (e.g. a whole-project
    # structural near-dup search). The fast `apex plan` / `apex ascend` board
    # skips these so the autonomous loop stays fast; they remain runnable
    # explicitly via `apex develop --objective <name>`.
    expensive: bool = False
    # When True, ``compile_objective`` gates each move against the IMPACTED tests
    # (those that import the changed module / its package) rather than the FULL
    # suite. Required for the stub-FILLING objectives (``implement-stub``,
    # ``tdd-implement``): their baseline suite is legitimately RED on a
    # multi-module project — every still-unimplemented stub fails its own tests —
    # so a correct per-module fill, gated by the whole suite, would be vetoed by an
    # unrelated still-red module and rolled back (the cross-module apply deadlock).
    # Impact-scoping runs the filled module's REAL importing tests (which genuinely
    # pass after the fill, so the "verified" stamp stays honest) and skips the
    # unrelated red ones, whose redness is pre-existing and not caused by this move.
    # The full suite remains the commit-time backstop (``scripts/verify.py``).
    # Default False: the cheap "tidy" objectives keep full-suite gating, so
    # existing idea/objective behaviour is unchanged.
    scope_verify: bool = False


_REGISTRY: dict[str, ObjectiveSpec] = {}
_DISCOVERED = False


def register(spec: ObjectiveSpec) -> ObjectiveSpec:
    """Register (or replace) an objective by name. Returns the spec, so it can
    be used as ``SPEC = register(ObjectiveSpec(...))``. Re-registering the same
    name (e.g. a module re-imported under test) is harmless — last write wins.

    SOUNDNESS LOCK (autonomy trust-floor): a self-registering objective MUST
    declare HOW it is sound in ``SOUNDNESS_STRATEGY`` before it can register. An
    objective absent from that manifest raises :class:`ValueError` HERE — at import
    — rather than skewing silently until the late self-audit, so the hands-off
    develop loop can never run an objective that has no reviewed soundness argument.
    The manifest already covers every current objective (the forward tripwire
    ``soundness_audit.strategy_completeness`` proves it), so this fires only for a
    NEW objective added without a strategy entry — the intended trip.

    ``SOUNDNESS_STRATEGY`` is read from the dependency-free leaf
    ``app.engine.soundness_manifest`` (NOT ``soundness_audit``): that leaf imports
    nothing from the engine, so this edge forms no import cycle — whereas importing
    ``soundness_audit`` would close ``develop_registry`` -> ``soundness_audit`` ->
    ``objective_compiler`` -> ``develop_registry``, the very cycle the module header
    keeps this registry clear of. Imported inside the function to keep module import
    cheap; the manifest is a tiny stdlib-only dict, so the call cost is negligible."""
    from app.engine.soundness_manifest import SOUNDNESS_STRATEGY

    if spec.name not in SOUNDNESS_STRATEGY:
        raise ValueError(
            f"develop objective {spec.name!r} has no declared soundness strategy — "
            "add it to SOUNDNESS_STRATEGY in app/engine/soundness_manifest.py (state "
            "HOW the transform is sound) before registering it. The autonomous develop "
            "loop refuses to run an objective with no reviewed soundness argument.")
    _REGISTRY[spec.name] = spec
    return spec


def objective(name: str, fitness: Callable[[str | Path], float]):
    """Decorator form: register the decorated *moves* function as objective
    ``name`` with the given ``fitness``. Returns the function unchanged.

        @objective("collapse-foo", _foo_fitness)
        def _foo_moves(project_root): ...
    """
    def _wrap(moves: Callable[[str | Path], list]):  # list[Move]
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


def expensive_names() -> set[str]:
    """Names of discovered objectives flagged ``expensive`` — a heavy fitness
    scan the fast plan/ascend board should skip (they stay runnable explicitly)."""
    return {name for name, spec in registered_specs().items() if spec.expensive}


def clear_registry() -> None:
    """Drop all registrations and reset discovery — for tests only."""
    global _DISCOVERED
    _REGISTRY.clear()
    _DISCOVERED = False
