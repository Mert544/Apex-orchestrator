"""Self-registering objective: dict-comprehension.

The transform lives in :mod:`app.execution.dict_comprehension`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective dict-comprehension` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.dict_comprehension import plan_dict_comprehension
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "dict-comprehension", plan_dict_comprehension,
    operator="dict_comprehension",
    description="apply dict-comprehension in {rel}",
)
