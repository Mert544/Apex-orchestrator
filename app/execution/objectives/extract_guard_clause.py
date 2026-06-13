"""Self-registering objective: extract-guard-clause.

The transform lives in :mod:`app.execution.extract_guard_clause`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective extract-guard-clause` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_extract_guard_clause`` over every own module, so
it collapses to a single :func:`register_module_objective` call — the shared
helper builds the identical ``_modules`` / ``fitness`` / ``moves`` trio.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.extract_guard_clause import plan_extract_guard_clause

register_module_objective(
    "extract-guard-clause", plan_extract_guard_clause,
    operator="extract_guard_clause",
    description="apply extract-guard-clause in {rel}",
)
