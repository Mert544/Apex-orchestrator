"""Self-registering objective: merge-isinstance.

Collapse ``isinstance(x, A) or isinstance(x, B)`` into ``isinstance(x, (A, B))``.
The transform lives in :mod:`app.execution.merge_isinstance`; this module only
names it as a develop objective and registers itself with the develop registry.
"""

from __future__ import annotations

from app.execution.merge_isinstance import plan_merge_isinstance
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "merge-isinstance", plan_merge_isinstance,
    operator="merge_isinstance",
    description="merge isinstance or-chains in {rel}",
)
