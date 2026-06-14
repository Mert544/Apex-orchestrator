"""Self-registering objective: remove-redundant-fstring.

The transform lives in :mod:`app.execution.remove_redundant_fstring`; this module
only names it as a develop objective and registers itself with the develop
registry, so it becomes a first-class
`apex develop --objective remove-redundant-fstring` (and shows up in `apex plan` /
`apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.remove_redundant_fstring import (
    plan_remove_redundant_fstring,
)

register_module_objective(
    "remove-redundant-fstring", plan_remove_redundant_fstring,
    operator="remove_redundant_fstring",
    description="apply remove-redundant-fstring in {rel}",
)
