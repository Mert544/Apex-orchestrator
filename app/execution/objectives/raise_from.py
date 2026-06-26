"""Self-registering develop objective: raise-from — chain a re-raised exception
to its cause (the B904 fix) as a first-class develop campaign.

This WIRES the ALREADY-BUILT
:func:`app.execution.semantic.transforms.raise_from.apply` transform onto the
autonomous develop surface. It adds NO new transform logic and NO new detector:
the fix — turning ``raise X(...)`` inside ``except E as err:`` into ``raise X(...)
from err`` — is produced VERBATIM by that engine, routed through the SAME
verified-with-rollback compiler every other develop move uses.

BEHAVIOUR-PRESERVING by construction. ``raise X(...) from err`` raises the SAME
exception ``X`` with the SAME control flow; it only sets ``__cause__`` so the
original traceback is restored (the ``from err`` chain). Nothing else changes —
a traceback-hygiene fix, behaviour-identical in the same class as a docstring or
an annotation. The transform already REFUSES (returns ``None``) when there is no
fixable ``raise X(...)`` or no ``except … as <name>`` binding to chain from
(inventing a binding would be a bigger edit than this transform promises) and
when the raise is multi-line (line surgery would be fragile). The
``_content_plan`` adapter additionally re-``ast.parse``s the rewrite before
recording it (the never-fake-green floor), so a malformed splice is never landed.

Standard one-``plan_fn``-over-every-module shape, registered via
``_base.register_module_objective`` — ``fitness`` is how many own modules still
carry a landable B904 (it ticks down to 0 when none remain) and there is one
``raise-from`` Move per such module. The plan is bound through
``objective_compiler._content_plan`` (the ``SemanticPatchResult`` → ``RenamePlan``
adapter the ``harden`` objective uses), re-derived against the project's CURRENT
state when the move runs so line numbers stay correct as earlier moves land.
``scope_verify`` is the default ``False`` (a behaviour-identical chain has no
red baseline a full-suite gate could wrongly veto) and it is NOT ``expensive``
(a pure-AST scan). Stdlib-only, zero-token, offline, idempotent (a second run
sees the ``from err`` it landed and refuses — a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan
from app.execution.objectives._base import register_module_objective


def plan_raise_from(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the raise-from (B904) plan for one module, or an honest no-op plan.

    Refuses a test/fixture file AND a non-library file (packaging / config / task /
    generated script) FIRST — Apex never edits the suite it is gated by, and a fix
    in a script nobody imports as an API is config noise (the same refusal model the
    broad single-file family applies via ``plan_source_rewrite``). The
    ``register_module_objective`` enumeration already feeds only own non-fixture
    modules, so this gate is belt-and-braces that also keeps a DIRECT
    ``plan_raise_from`` call honest (mirroring ``harden._landable``).

    Otherwise binds the already-built
    :func:`app.execution.semantic.transforms.raise_from.apply` transform through
    ``objective_compiler._content_plan`` — the shared ``SemanticPatchResult`` →
    :class:`RenamePlan` adapter (read the module, run ``apply``, record the single
    rewrite with its original for rollback, re-parse before recording) the
    ``harden`` objective uses. Imported lazily and re-run per call so the plan
    re-derives against the project's CURRENT state when the move runs (line numbers
    shift as earlier moves land), exactly like every other develop objective's
    ``build_plan`` thunk. An empty plan means nothing to do here — no ``except …
    as <name>`` binding with a fixable ``raise X(...)`` — a no-op, not a failure."""
    from app.engine.objective_compiler import _content_plan
    from app.execution.cross_file_rename import (
        _is_fixture_path,
        _is_non_library_file,
    )
    from app.execution.semantic.transforms import raise_from

    if _is_fixture_path(module_rel) or _is_non_library_file(module_rel):
        return RenamePlan(old=module_rel, new="raise-from")  # never a suite/script edit
    return _content_plan(project_root, module_rel, raise_from.apply, "raise-from")


register_module_objective(
    "raise-from", plan_raise_from,
    operator="raise_from",
    description="chain a re-raised exception to its cause (raise … from err) in {rel}",
)
