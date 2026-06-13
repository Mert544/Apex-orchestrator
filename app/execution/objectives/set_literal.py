"""Self-registering objective: set-literal.

The transform lives in :mod:`app.execution.set_literal`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective set-literal` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.set_literal import plan_set_literal

register_module_objective(
    "set-literal", plan_set_literal,
    operator="set_literal",
    description="apply set-literal in {rel}",
)
