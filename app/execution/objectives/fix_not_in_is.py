"""Self-registering objective: fix-not-in-is.

The transform lives in :mod:`app.execution.fix_not_in_is`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective fix-not-in-is` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.fix_not_in_is import plan_fix_not_in_is
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "fix-not-in-is", plan_fix_not_in_is,
    operator="fix_not_in_is",
    description="apply fix-not-in-is in {rel}",
)
