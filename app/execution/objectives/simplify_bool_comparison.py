"""Self-registering objective: simplify-bool-comparison.

The transform lives in :mod:`app.execution.simplify_bool_comparison`; this module
only names it as a develop objective and registers itself with the develop
registry, so it becomes a first-class
`apex develop --objective simplify-bool-comparison` (and shows up in `apex plan` /
`apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.simplify_bool_comparison import (
    plan_simplify_bool_comparison,
)

register_module_objective(
    "simplify-bool-comparison", plan_simplify_bool_comparison,
    operator="simplify_bool_comparison",
    description="apply simplify-bool-comparison in {rel}",
)
