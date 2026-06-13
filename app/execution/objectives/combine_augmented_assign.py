"""Self-registering objective: combine-augmented-assign.

The transform lives in :mod:`app.execution.combine_augmented_assign`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective combine-augmented-assign` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_combine_augmented_assign`` over every own module, so
it collapses to a single :func:`register_module_objective` call — the shared
helper builds the identical ``_modules`` / ``fitness`` / ``moves`` trio.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.combine_augmented_assign import plan_combine_augmented_assign

register_module_objective(
    "combine-augmented-assign", plan_combine_augmented_assign,
    operator="combine_augmented_assign",
    description="apply combine-augmented-assign in {rel}",
)
