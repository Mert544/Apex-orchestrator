"""Self-registering objective: modernize-typing.

Land the PEP 585 / PEP 604 typing modernization on a project's own module —
``typing.List[x]`` -> ``list[x]``, ``Dict``/``Tuple``/``Set``/``FrozenSet``/``Type``
likewise, ``Optional[X]`` -> ``X | None``, ``Union[A, B]`` -> ``A | B``,
``typing.Text`` -> ``str`` — in ANNOTATION POSITIONS only. The canonical
expensive-paid-LLM chore, written deterministically and for free.

The detection + minimal AST rewrite live in :mod:`app.execution.modernize_typing`
(``modernize_typing``); this module only names it as a develop objective and
registers itself with the develop registry. Standard single-file shape, so it
reuses ``plan_source_rewrite`` — the same suite-gated, auto-rollback develop loop
every objective uses, and the plan layer refuses test/fixture and non-library
files.

THE LOAD-BEARING GATE (in the transform, restated here): a rewrite fires ONLY when
the module already carries ``from __future__ import annotations`` — so every
annotation is a deferred PEP 563 string and both ``list[x]`` and ``X | None`` are
runtime-safe on ANY Python that parses them. With NO future-import the transform
REFUSES (an honest no-op); the recoverable composition is to run the existing
``add-from-future-annotations`` objective first. The transform also refuses a
``from typing import *`` / ambiguous-binding / shadowed-name module and a
``Tuple[()]`` or string-literal annotation (wave-1 sharp edges), and never touches
a ``typing`` name in EXPRESSION position. WAVE-1 SCOPE CUT: the (now possibly
unused) ``from typing import ...`` import line is left alone — ``remove-unused-imports``
cleans it later, and an unused import is behaviour-identical.

Behaviour-preserving (the future-import gate makes the deferred annotations
version-safe; only annotation-position spans are rewritten), value-identical at
runtime. Deterministic, stdlib-only, zero-token, idempotent (a second run finds no
legacy spelling and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.modernize_typing import modernize_typing
from app.execution.objectives._base import register_module_objective


def plan_modernize_typing(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the modernize-typing plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture and non-library, read, run ``modernize_typing``, record the one
    in-place rewrite with its original so the verified-apply engine can roll it
    back). An empty plan means nothing to do here — no future-import, no migratable
    typing name, an ambiguous/star/shadowed binding, a sharp-edge annotation, or
    simply no legacy spelling — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "modernize_typing", modernize_typing)


register_module_objective(
    "modernize-typing", plan_modernize_typing,
    operator="modernize_typing",
    description="modernize typing annotations to PEP 585/604 in {rel}",
)
