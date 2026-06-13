"""Self-registering objective: simplify-dict-get.

Rewrite ``x[k] if k in x else d`` into ``x.get(k, d)``. The transform lives in
:mod:`app.execution.dict_get`; this module only names it as a develop objective
and registers itself with the develop registry.
"""

from __future__ import annotations

from app.execution.dict_get import plan_simplify_dict_get
from app.execution.objectives._base import register_module_objective

register_module_objective(
    "simplify-dict-get", plan_simplify_dict_get,
    operator="simplify_dict_get",
    description="simplify dict-get ternaries in {rel}",
)
