"""Self-registering objective: infer-type-hints.

Land PROVABLE type annotations on a project's own code — the concrete
contribution a student would otherwise pay an LLM for. Where ``apex insights``
only MEASURES type-hint coverage, this WRITES the hints: a ``-> T`` inferred
from agreeing literal returns and a ``param: T`` inferred from a non-None
literal default, never a guess.

The inference + plan live in
:mod:`app.execution.semantic.transforms.type_annotations`
(``plan_type_annotations``); this module only names it as a develop objective
and registers itself with the develop registry. Standard module-objective shape
(one ``plan_fn`` per own module), so it reuses ``_base.register_module_objective``
— same suite-gated, auto-rollback develop loop as every other objective, and the
plan layer refuses test/fixture files. Deterministic, stdlib-only, zero-token.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.semantic.transforms.type_annotations import plan_type_annotations

register_module_objective(
    "infer-type-hints", plan_type_annotations,
    operator="infer_type_hints",
    description="add provable type hints in {rel}",
)
