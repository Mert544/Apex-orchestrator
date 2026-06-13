"""Self-registering objective: remove-double-negation.

The transform lives in :mod:`app.execution.remove_double_negation`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective remove-double-negation` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_remove_double_negation`` over every own module, so
it collapses to a single :func:`register_module_objective` call — the shared
helper builds the identical ``_modules`` / ``fitness`` / ``moves`` trio.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.remove_double_negation import plan_remove_double_negation

register_module_objective(
    "remove-double-negation", plan_remove_double_negation,
    operator="remove_double_negation",
    description="apply remove-double-negation in {rel}",
)
