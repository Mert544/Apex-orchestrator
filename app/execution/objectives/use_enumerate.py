"""Self-registering objective: use-enumerate.

The transform lives in :mod:`app.execution.use_enumerate`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective use-enumerate` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_use_enumerate`` over every own module, so
it collapses to a single :func:`register_module_objective` call — the shared
helper builds the identical ``_modules`` / ``fitness`` / ``moves`` trio.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.use_enumerate import plan_use_enumerate

register_module_objective(
    "use-enumerate", plan_use_enumerate,
    operator="use_enumerate",
    description="apply use-enumerate in {rel}",
)
