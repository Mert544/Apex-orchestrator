"""Self-registering objective: fix-assert-tuple.

The transform lives in :mod:`app.execution.fix_assert_tuple`; this module only
names it as a develop objective and registers itself with the develop registry,
so it becomes a first-class `apex develop --objective fix-assert-tuple` (and
shows up in `apex plan` / `apex ascend`) with no hub edit.
"""

from __future__ import annotations

from app.execution.fix_assert_tuple import plan_fix_assert_tuple
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "fix-assert-tuple", plan_fix_assert_tuple,
    operator="fix_assert_tuple",
    description="apply fix-assert-tuple in {rel}",
)
