"""Self-registering objective: chain-comparison.

The transform lives in :mod:`app.execution.chain_comparison`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective chain-comparison` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.chain_comparison import plan_chain_comparison
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "chain-comparison", plan_chain_comparison,
    operator="chain_comparison",
    description="apply chain-comparison in {rel}",
)
