"""Self-registering objective: percent-to-fstring.

The transform lives in :mod:`app.execution.percent_to_fstring`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective percent-to-fstring` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.percent_to_fstring import plan_percent_to_fstring

register_module_objective(
    "percent-to-fstring", plan_percent_to_fstring,
    operator="percent_to_fstring",
    description="convert '%s'-formatting to f-strings in {rel}",
)
