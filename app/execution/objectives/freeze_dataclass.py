"""Self-registering objective: freeze-dataclass.

Land ``frozen=True`` on a project's own ``@dataclass`` whose fields are NEVER
mutated anywhere in the project's own source — the immutable + hashable form a
linter only FLAGS but Apex WRITES. Behaviour-preserving when (and ONLY when) no
code path ever assigns, augments, deletes, or ``setattr``-s one of the class's
fields; the engine proves that conservatively across the WHOLE project before a
single decorator is touched.

The detection + minimal decorator rewrite live in
:mod:`app.execution.freeze_dataclass` (``freeze_dataclass_decorator``); this
module only names it as a develop objective and registers itself with the develop
registry. UNLIKE the standard single-file objectives, freeze-dataclass needs
WHOLE-PROJECT context (the conservative mutation / used-as-base over-approximation
spans every own module), so it builds its own ``RenamePlan`` — refusing
test/fixture, reading the target, running the transform with the project's own
sources as the mutation scan, and recording the one in-place rewrite with its
original so the suite-gated apply engine can roll it back. The transform refuses
(an honest no-op) a module with no freezable dataclass: already frozen, has a
base / is subclassed elsewhere, a field mutated anywhere, no fields, or
unparseable source.

The soundness story — why a green suite ALONE is not enough, and why the static
whole-project over-approximation is required — is documented in the engine module.
The remaining residual risk (a dynamic mutation a static scan cannot see, e.g.
``setattr(o, some_var, ...)``) is caught by the objective layer's full-suite gate
+ byte-for-byte rollback, the same engine every objective uses. Deterministic,
stdlib-only, zero-token, idempotent (a second run sees ``frozen=True`` and is a
byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.freeze_dataclass import (
    freeze_dataclass_decorator,
    project_sources,
)
from app.execution.objectives._base import register_module_objective


def plan_freeze_dataclass(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the freeze-dataclass plan for one module, or an honest no-op.

    Reuses the shared single-file ``plan_source_rewrite`` (refuse test/fixture,
    read, run the transform, record the one in-place rewrite with its original so
    the verified-apply engine can roll it back). The one twist this objective adds
    over the standard single-file shape: its transform needs WHOLE-PROJECT context
    — the conservative mutation / used-as-base over-approximation spans every own
    module — so the transform is a closure that, given the module's source,
    gathers the project's own sources and runs ``freeze_dataclass_decorator`` with
    that scan set. An empty plan means nothing to do here — no freezable dataclass,
    or the module does not parse — a no-op, not a failure."""

    def _transform(source: str) -> str | None:
        sources = project_sources(project_root, module_rel, source)
        return freeze_dataclass_decorator(source, sources)

    return plan_source_rewrite(
        project_root, module_rel, "freeze_dataclass", _transform)


register_module_objective(
    "freeze-dataclass", plan_freeze_dataclass,
    operator="freeze_dataclass",
    description="add frozen=True to {rel}",
)
