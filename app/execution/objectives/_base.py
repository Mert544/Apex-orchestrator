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

import inspect
from collections.abc import Callable
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register


def _accepts_source_kwarg(plan_fn: Callable[..., object]) -> bool:
    """True when ``plan_fn`` declares a ``source`` parameter (or ``**kwargs``).

    Computed ONCE at registration time (below), never per-call, so this costs
    nothing extra on the hot path. The Stage-1 ``source=`` convention
    (``plan_extract_constant``, ``plan_source_rewrite``, ``plan_simplify_bool_return``,
    …) is OPT-IN per transform: the vast majority of ``plan_fn``s registered
    through this helper still have the original fixed ``(project_root,
    module_rel)`` signature and would raise ``TypeError`` on an unexpected
    ``source=`` keyword, so threading it blindly would break them. Introspecting
    the signature keeps every such objective byte-identical (called exactly as
    before) while a ``plan_fn`` that HAS adopted ``source=`` gets the cached text
    threaded straight in."""
    try:
        params = inspect.signature(plan_fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.name == "source" or p.kind is inspect.Parameter.VAR_KEYWORD
        for p in params
    )


def register_module_objective(
    name: str,
    plan_fn: Callable[..., object],
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

    Both ``_modules`` (backing ``fitness``) and ``moves`` scan ``_own_modules()``
    — the parse-once source index — directly, and each already carries the
    module's ``(rel, source)`` pair from that ONE scan. When ``plan_fn`` has
    adopted the optional ``source=`` parameter (:func:`_accepts_source_kwarg`),
    that cached text is threaded straight into every call — the fitness scan,
    the candidate-build scan, AND the landed move's own ``build_plan`` thunk (no
    OTHER move in the same pass ever targets the same module, so the captured
    text can't go stale within one pass; a cross-pass edit is still caught by
    the apply-time stale-content check). A ``plan_fn`` that hasn't adopted
    ``source=`` is called exactly as before — byte-identical.
    """
    suffix = target_suffix or name
    threads_source = _accepts_source_kwarg(plan_fn)

    def _plan_for(project_root: str | Path, rel: str, source: str) -> object:
        if threads_source:
            return plan_fn(project_root, rel, source=source)
        return plan_fn(project_root, rel)

    def _modules(project_root: str | Path) -> list[str]:
        from app.engine.objective_compiler import _own_modules

        return [rel for rel, src in _own_modules(project_root)
                if _plan_for(project_root, rel, src).new_contents]

    def fitness(project_root: str | Path) -> float:
        """Fitness = how many own modules ``plan_fn`` would still change."""
        return float(len(_modules(project_root)))

    def moves(project_root: str | Path) -> list:
        from app.engine.objective_compiler import Move, _own_modules

        out: list = []
        for rel, src in _own_modules(project_root):
            if _plan_for(project_root, rel, src).new_contents:
                out.append(Move(
                    operator=operator,
                    target=f"{rel}:{suffix}",
                    description=description.format(rel=rel),
                    build_plan=lambda r=rel, s=src: _plan_for(project_root, r, s),
                ))
        return out

    return register(ObjectiveSpec(name=name, fitness=fitness, moves=moves))
