"""Self-registering objective: synthesize-dunders.

Land the canonical ``__repr__`` / ``__eq__`` / ``__hash__`` on a project's own regular
(non-``@dataclass``) class whose ``__init__`` carries pure ``self.x = x`` plumbing copies
and that is MISSING ``__repr__`` and/or ``__eq__``. The SIBLING of dataclassify for the
classes dataclassify must REFUSE (a real ``__init__`` body beyond copies, a base class,
extra methods) but that still deserve the value semantics ``@dataclass`` would have given
them for free: it splices ONLY the canonical TOTAL forms ``@dataclass`` itself emits over
the PROVEN pure-copy field set (already trusted across the codebase via dataclassify), so
the change is an honest under-claim — it never invents a field.

The detection + minimal splice live in :mod:`app.execution.dunder_synthesis`
(``synthesize_dunders``); this module only names it as a develop objective and registers
itself with the develop registry. Like freeze-dataclass (and UNLIKE the @final / add-slots
family), it threads WHOLE-PROJECT context via the tests-EXCLUDING ``project_sources`` — NOT
the tests-inclusive ``all_module_sources``: the inherited-``__eq__`` contract is resolved
against the project's OWN classes, and a wrong ``__eq__`` is a RUNTIME difference the pytest
suite CATCHES (and ``apply_rename`` byte-rolls-back), so tests need not be in the static
scan set (the exact freeze-dataclass rationale at ``freeze_dataclass.py:538``). So the
transform is a closure that, given the module's source, gathers the project's own sources
and runs ``synthesize_dunders`` with that scan set — the inherited-contract refusal reads
it to prove no resolvable base (transitively) defines ``__eq__`` (and refuses an external /
un-resolvable base). It still reuses the shared single-file ``plan_source_rewrite`` (refuse
test/fixture + non-library files, read, run the transform, record the one in-place rewrite
with its original so the suite-gated apply engine can roll it back).

NOT expensive and NOT scope_verify — the in-process AST base scan is cheap (like add-slots,
which keeps its whole-project scan in-process and stays non-expensive), and a wrong
synthesized dunder is a RUNTIME mismatch the FULL default suite gate catches, so it takes
the default ``ObjectiveSpec`` flags (full-suite gate, no impact-scoping). Deterministic,
stdlib-only, zero-token, idempotent (a second run sees the dunders it landed and is a
byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.dunder_synthesis import synthesize_dunders
from app.execution.freeze_dataclass import project_sources
from app.execution.objectives._base import register_module_objective


def plan_synthesize_dunders(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the synthesize-dunders plan for one module, or an honest no-op.

    Reuses the shared single-file ``plan_source_rewrite`` (refuse test/fixture, read, run
    the transform, record the one in-place rewrite with its original so the verified-apply
    engine can roll it back). The one twist over the standard single-file shape: its
    transform needs WHOLE-PROJECT context — the inherited-``__eq__`` base scan resolves a
    class's base against the project's OWN classes (via the tests-EXCLUDING
    ``project_sources``, because a wrong ``__eq__`` is a runtime difference the suite
    catches, so tests need not be in the scan set) — so the transform is a closure that,
    given the module's source, gathers the project's own sources and runs
    ``synthesize_dunders`` with that scan set. An empty plan means nothing to do here — no
    eligible class, or the module does not parse — a no-op, not a failure."""

    def _transform(source: str) -> str | None:
        sources = project_sources(project_root, module_rel, source)
        return synthesize_dunders(source, sources)

    return plan_source_rewrite(
        project_root, module_rel, "synthesize_dunders", _transform)


register_module_objective(
    "synthesize-dunders", plan_synthesize_dunders,
    operator="synthesize_dunders",
    description="generate __repr__/__eq__ from declared fields in {rel}",
)
