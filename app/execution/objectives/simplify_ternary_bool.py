"""Self-registering objective: simplify-ternary-bool.

The transform lives in :mod:`app.execution.simplify_ternary_bool`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective simplify-ternary-bool` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.simplify_ternary_bool import plan_simplify_ternary_bool

register_module_objective(
    "simplify-ternary-bool", plan_simplify_ternary_bool,
    operator="simplify_ternary_bool",
    description="apply simplify-ternary-bool in {rel}",
)
