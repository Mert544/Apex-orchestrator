"""Self-registering objective: remove-pointless-pass.

The transform lives in :mod:`app.execution.remove_pointless_pass`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective remove-pointless-pass` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_remove_pointless_pass`` over every own module, so
it collapses to a single :func:`register_module_objective` call — the shared
helper builds the identical ``_modules`` / ``fitness`` / ``moves`` trio.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.remove_pointless_pass import plan_remove_pointless_pass

register_module_objective(
    "remove-pointless-pass", plan_remove_pointless_pass,
    operator="remove_pointless_pass",
    description="apply remove-pointless-pass in {rel}",
)
