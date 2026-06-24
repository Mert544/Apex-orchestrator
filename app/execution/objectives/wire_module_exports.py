"""Self-registering objective: wire-module-exports.

Land a module-level ``__all__ = [...]`` on a leaf ``.py`` module that DEFINES
public symbols but never declares one — the explicit public-surface line a student
or team writes by hand on a maturing module. Where a linter only NOTES the missing
``__all__``, this WRITES it: ``__all__`` pinned to EXACTLY the module's current
default star-import set (every module-level bound public name), inserted after the
docstring + the import block.

This is the LEAF-MODULE sibling of ``wire-exports`` — distinct surface. wire-exports
populates a PACKAGE ``__init__.py`` with ``from .module import Name`` re-exports;
this declares the ``__all__`` of a module that defines its public symbols DIRECTLY,
adding no imports and re-exporting nothing.

The detection + minimal rewrite live in :mod:`app.execution.module_exports`
(``add_module_all``); this module only names it as a develop objective and registers
itself with the develop registry. Standard single-file shape, so it reuses
``plan_source_rewrite`` — the same suite-gated, auto-rollback develop loop every
objective uses, and the plan layer refuses test/fixture files.

Soundness is STRUCTURAL and near-total: ``__all__`` is consulted ONLY by
``from module import *``, and the emitted set EQUALS the current default star set,
so ``import *`` imports the identical names and every other import form is
unaffected — behaviour-identical, independent of any test suite. The transform
REFUSES (a no-op) a module that already declares ``__all__`` (idempotent), one with
a ``from x import *`` (the default set is unknowable statically), one with no public
names (an empty ``__all__`` would be noise), one with an unmodelled top-level binder
(control flow / complex unpacking — the set cannot be proven), or unparseable
source. Deterministic, stdlib-only, zero-token, idempotent (a second run sees the
``__all__`` it landed and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.module_exports import add_module_all
from app.execution.objectives._base import register_module_objective


def plan_wire_module_exports(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the wire-module-exports plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture, read, run ``add_module_all``, record the one in-place rewrite
    with its original so the verified-apply engine can roll it back). An empty
    plan means nothing to do here — the module already declares ``__all__``, has a
    ``from x import *``, has no public names, has an unmodelled top-level binder, or
    does not parse — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "wire_module_exports", add_module_all)


register_module_objective(
    "wire-module-exports", plan_wire_module_exports,
    operator="wire_module_exports",
    description="declare __all__ in {rel}",
)
