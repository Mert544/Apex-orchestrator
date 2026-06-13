"""Self-registering objective: fstring-convert.

Rewrite a simple ``"...{}...".format(args)`` call into the equivalent f-string.
The transform lives in :mod:`app.execution.fstring_convert`; this module only
names it as a develop objective and registers itself with the develop registry.
"""

from __future__ import annotations

from app.execution.fstring_convert import plan_fstring_convert
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "fstring-convert", plan_fstring_convert,
    operator="fstring_convert",
    description="convert .format() to f-strings in {rel}",
)
