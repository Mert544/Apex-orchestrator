"""Self-registering objective: merge-nested-if.

The transform lives in :mod:`app.execution.merge_nested_if`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective merge-nested-if` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_merge_nested_if`` over every own module, so
it collapses to a single :func:`register_module_objective` call — the shared
helper builds the identical ``_modules`` / ``fitness`` / ``moves`` trio.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.merge_nested_if import plan_merge_nested_if

register_module_objective(
    "merge-nested-if", plan_merge_nested_if,
    operator="merge_nested_if",
    description="apply merge-nested-if in {rel}",
)
