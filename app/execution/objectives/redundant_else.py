"""Self-registering objective: remove-redundant-else.

Drop an ``else`` whose ``if`` branch already exits (its body ends in a
terminal), dedenting the else-body so it stands as siblings after the ``if``.
The transform lives in :mod:`app.execution.redundant_else`; this module only
names it as a develop objective and registers itself with the develop registry.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.redundant_else import plan_remove_redundant_else

register_module_objective(
    "remove-redundant-else", plan_remove_redundant_else,
    operator="remove_redundant_else",
    description="remove redundant else after a terminal in {rel}",
    target_suffix="redundant-else",
)
