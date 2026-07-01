"""Self-registering objective: add-functools-wraps.

Land ``@functools.wraps(<callee>)`` on a decorator-factory's inner WRAPPER
function that calls its outer's single parameter but carries no ``wraps`` yet —
the one-line metadata fix a student/team forgets when hand-writing a decorator
factory. In-repo target this objective was built against:
``app/agents/swarm_stability.py``'s ``with_timeout`` — ``decorator``'s inner
``wrapper`` calls ``func`` (twice: ``func.__name__`` and
``func(*args, **kwargs)``) but never carries ``@functools.wraps(func)``.

BEHAVIOUR-IDENTICAL by construction (metadata-only): ``functools.wraps`` copies
``__module__``/``__name__``/``__qualname__``/``__doc__``/``__dict__`` and sets
``__wrapped__`` — it changes NOT ONE byte of control flow, return value, or
exception behaviour. Same soundness class as ``add-from-future-annotations`` /
``document-signature`` (reparse-identical-or-refuse, no test suite needed).

The detection + minimal rewrite live in
:mod:`app.execution.functools_wraps` (``add_functools_wraps``); this module
only names it as a develop objective and registers itself with the develop
registry. Standard single-file shape, so it reuses ``plan_source_rewrite`` —
the same suite-gated, auto-rollback develop loop every objective uses, and the
plan layer refuses test/fixture/non-library files. The transform refuses (a
no-op) a module with no qualifying decorator-factory shape, an already-wrapped
wrapper, an ambiguous callee (more than one outer parameter called inside the
wrapper), a callee name reassigned/shadowed before the wrapper closes over it,
more than one (or zero) direct nested def matching the returned name, a
wrapper that is not the direct ``return`` value, or unparseable source.

Deterministic (pure AST walk + line splice, no clock/random), stdlib-only,
zero-token, idempotent (a second run sees the ``@functools.wraps`` it landed
and refuses).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.functools_wraps import add_functools_wraps
from app.execution.objectives._base import register_module_objective


def plan_add_functools_wraps(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the add-functools-wraps plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture/non-library, read, run ``add_functools_wraps``, record the one
    in-place rewrite with its original so the verified-apply engine can roll it
    back). An empty plan means nothing to do here — no qualifying
    decorator-factory shape, or the module does not parse — a no-op, not a
    failure."""
    return plan_source_rewrite(
        project_root, module_rel, "add_functools_wraps", add_functools_wraps)


register_module_objective(
    "add-functools-wraps", plan_add_functools_wraps,
    operator="add_functools_wraps",
    description="add @functools.wraps to an unwrapped decorator wrapper in {rel}",
)
