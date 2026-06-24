"""Self-registering objective: add-final.

Land ``@typing.final`` on a project's own top-level class that is PROVABLY never
subclassed anywhere in the project — the leaf-class design intent a careful author
annotates by hand. ``@typing.final`` is a PURE runtime no-op (it only sets
``__final__`` and is consulted by type checkers), so the change is behaviour-
preserving BY CONSTRUCTION; the only honesty risk — a false "final" on a class that
IS subclassed — is closed STRUCTURALLY by a whole-project over-approximate subclass
scan, not by the suite. Where a linter only FLAGS the opportunity, Apex WRITES it,
deterministically and for free.

The detection + minimal rewrite live in :mod:`app.execution.final_marker`
(``add_final_decorator``); this module only names it as a develop objective and
registers itself with the develop registry. UNLIKE the standard single-file
objectives, add-final needs WHOLE-PROJECT context (the conservative used-as-base
over-approximation spans every own module), so — like freeze-dataclass — its
transform is a closure that gathers the project's own sources as the subclass scan
set before running the marker. It still reuses the shared single-file
``plan_source_rewrite`` (refuse test/fixture, read, run the transform, record the
one in-place rewrite with its original so the suite-gated apply engine can roll it
back). The transform refuses (an honest no-op) a module with no finalizable class:
the class is subclassed (incl. via a dotted base), already ``@final``, an abstract
base / protocol / enum, the name ``final`` cannot be bound unambiguously to
``typing.final``, or the module does not parse.

``typing.final`` exists since Python 3.8, so this lands on the 3.10 floor with NO
version gate. Deterministic, stdlib-only, zero-token, idempotent (a second run sees
the ``@final`` it landed and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.final_marker import add_final_decorator, project_sources
from app.execution.objectives._base import register_module_objective


def plan_add_final(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the add-final plan for one module, or an honest no-op.

    Reuses the shared single-file ``plan_source_rewrite`` (refuse test/fixture,
    read, run the transform, record the one in-place rewrite with its original so
    the verified-apply engine can roll it back). The one twist over the standard
    single-file shape: its transform needs WHOLE-PROJECT context — the conservative
    used-as-base over-approximation spans every own module — so the transform is a
    closure that, given the module's source, gathers the project's own sources and
    runs ``add_final_decorator`` with that scan set. An empty plan means nothing to
    do here — no finalizable class, or the module does not parse — a no-op, not a
    failure."""

    def _transform(source: str) -> str | None:
        sources = project_sources(project_root, module_rel, source)
        return add_final_decorator(source, sources)

    return plan_source_rewrite(project_root, module_rel, "add_final", _transform)


register_module_objective(
    "add-final", plan_add_final,
    operator="add_final",
    description="add @final to {rel}",
)
