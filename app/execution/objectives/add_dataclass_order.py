"""Self-registering objective: add-dataclass-order.

Land ``order=True`` on a project's own ``@dataclass`` that does NOT already set
``order=`` and defines NONE of the comparison dunders ``__lt__``/``__le__``/
``__gt__``/``__ge__`` itself — the sortable / orderable form a linter only FLAGS
but Apex WRITES. ``@dataclass(order=True)`` generates the four comparison
operators from the field tuple, so instances compare and sort by their fields;
on a value class that has none of them today (``a < b`` raises ``TypeError``) this
is a runtime-ADDITIVE modernization. The dataclass sibling of ``freeze-dataclass``
(``frozen=True``) and ``seal-total-ordering`` (``@functools.total_ordering``).

The detection + minimal decorator rewrite live in
:mod:`app.execution.dataclass_order` (``add_dataclass_order``); this module only
names it as a develop objective and registers itself. Standard single-file shape —
no whole-project scan is needed (the orderability proof is purely intra-module:
provably-stdlib ``@dataclass`` provenance, no existing ``order=`` / ``eq=False`` /
``**``-unpacking, and no hand-written ordering dunder in the body) — so it reuses
``plan_source_rewrite`` directly. The transform refuses (a no-op) a module with no
orderable dataclass: not a provably-stdlib ``@dataclass`` (pydantic / local
shadow), already ``order=`` (any value), ``eq=False`` set, a ``**``-unpacking or
multi-line/commented decorator, a body defining any of the four ordering dunders,
or unparseable source.

``dataclass(order=)`` exists since Python 3.7, so this lands on the 3.10 floor with
NO version gate. Deterministic (pure AST walk + line splice, no clock/random),
stdlib-only, zero-token, idempotent (a second run sees the ``order=True`` it landed
and is a byte-identical no-op). The remaining residual risk — a field type that is
not orderable, only surfacing when something sorts an instance — is caught by the
objective layer's full-suite gate + byte-for-byte rollback.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.dataclass_order import add_dataclass_order
from app.execution.objectives._base import register_module_objective


def plan_add_dataclass_order(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the add-dataclass-order plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse
    test/fixture + non-library files, read, run ``add_dataclass_order``, record the
    one in-place rewrite with its original so the verified-apply engine can roll it
    back). An empty plan means nothing to do here — no orderable dataclass, or the
    module does not parse — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "add_dataclass_order",
        add_dataclass_order)


register_module_objective(
    "add-dataclass-order", plan_add_dataclass_order,
    operator="add_dataclass_order",
    description="add order=True to a stdlib @dataclass in {rel}",
)
