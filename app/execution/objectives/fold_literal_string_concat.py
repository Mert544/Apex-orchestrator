"""Self-registering objective: fold-literal-string-concat.

The transform lives in :mod:`app.execution.fold_literal_string_concat`; this
module only names it as a develop objective and registers itself with the
develop registry, so it becomes a first-class
`apex develop --objective fold-literal-string-concat` (and shows up in
`apex plan` / `apex ascend`) with no hub edit.

This is a STANDARD spec: it runs one ``plan_fold_literal_string_concat`` over
every own module, so it collapses to a single :func:`register_module_objective`
call — the shared helper builds the identical ``_modules`` / ``fitness`` /
``moves`` trio.
"""

from __future__ import annotations

from app.execution.fold_literal_string_concat import (
    plan_fold_literal_string_concat,
)
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "fold-literal-string-concat", plan_fold_literal_string_concat,
    operator="fold_literal_string_concat",
    description="apply fold-literal-string-concat in {rel}",
)
