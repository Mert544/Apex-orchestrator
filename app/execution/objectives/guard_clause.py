"""Self-registering objective: guard-clause.

The transform lives in :mod:`app.execution.guard_clause`; this module only names
it as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective guard-clause` (and shows up in
`apex plan` / `apex ascend`) with no hub edit. It is the sibling of
extract-guard-clause, covering the trailing-``if``-after-setup shape that one
leaves alone.
"""

from __future__ import annotations

from app.execution.guard_clause import plan_guard_clause
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "guard-clause", plan_guard_clause,
    operator="guard_clause",
    description="apply guard-clause in {rel}",
)
