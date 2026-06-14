"""Self-registering objective: simplify-negated-comparison.

The transform lives in :mod:`app.execution.simplify_negated_comparison`; this
module only names it as a develop objective and registers itself with the develop
registry, so it becomes a first-class
`apex develop --objective simplify-negated-comparison` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.simplify_negated_comparison import (
    plan_simplify_negated_comparison,
)

register_module_objective(
    "simplify-negated-comparison", plan_simplify_negated_comparison,
    operator="simplify_negated_comparison",
    description="apply simplify-negated-comparison in {rel}",
)
