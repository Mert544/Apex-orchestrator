"""Self-registering objective: simplify-len-comparison.

The transform lives in :mod:`app.execution.simplify_len_comparison`; this module only names it
as a develop objective and registers itself with the develop registry, so it
becomes a first-class `apex develop --objective simplify-len-comparison` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_simplify_len_comparison`` over every own module, so
it collapses to a single :func:`register_module_objective` call — the shared
helper builds the identical ``_modules`` / ``fitness`` / ``moves`` trio.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.simplify_len_comparison import plan_simplify_len_comparison

register_module_objective(
    "simplify-len-comparison", plan_simplify_len_comparison,
    operator="simplify_len_comparison",
    description="apply simplify-len-comparison in {rel}",
)
