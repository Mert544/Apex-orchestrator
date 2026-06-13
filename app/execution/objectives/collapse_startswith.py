"""Self-registering objective: collapse-startswith.

Collapse ``x.startswith(a) or x.startswith(b)`` into ``x.startswith((a, b))``
(and the same for ``.endswith``). The transform lives in
:mod:`app.execution.startswith_tuple`; this module registers it as an objective.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.startswith_tuple import plan_collapse_startswith

register_module_objective(
    "collapse-startswith", plan_collapse_startswith,
    operator="collapse_startswith",
    description="collapse startswith/endswith or-chains in {rel}",
)
