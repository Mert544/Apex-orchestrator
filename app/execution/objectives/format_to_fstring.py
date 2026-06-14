"""Self-registering objective: format-to-fstring.

The transform lives in :mod:`app.execution.format_to_fstring`; this module only
names it as a develop objective and registers itself with the develop registry,
so it becomes a first-class ``apex develop --objective format-to-fstring`` (and
shows up in ``apex plan`` / ``apex ascend``) with no hub edit.
"""

from __future__ import annotations

from app.execution.format_to_fstring import plan_format_to_fstring
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "format-to-fstring", plan_format_to_fstring,
    operator="format_to_fstring",
    description="convert str.format() calls to f-strings in {rel}",
)
