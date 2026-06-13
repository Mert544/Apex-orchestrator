"""Self-registering objective: combine-nested-with.

Collapse ``with A:\\n    with B:`` into ``with A, B:``. The transform lives in
:mod:`app.execution.nested_with`; this module only names it as a develop
objective and registers itself with the develop registry.
"""

from __future__ import annotations

from app.execution.nested_with import plan_combine_nested_with
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "combine-nested-with", plan_combine_nested_with,
    operator="combine_nested_with",
    description="combine nested with-statements in {rel}",
)
