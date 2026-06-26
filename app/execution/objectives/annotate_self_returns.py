"""Self-registering develop objective: annotate-self-returns.

Land a ``-> "<EnclosingClass>"`` return annotation — a forward-ref STRING literal,
NOT ``typing.Self`` (so NO import and NO version gate) — on the one return shape
the ``infer-type-hints`` literal oracle deliberately REFUSES: a method whose every
value-return is ``self`` (a fluent/builder API), and a ``@classmethod`` whose every
value-return is ``cls(...)`` (an alternative constructor). Both are provable from
Python's LANGUAGE CONTRACT — ``self`` is an instance of its own class, ``cls(...)``
constructs one (subclass is-a holds, so the bound is sound) — yet the literal
oracle returns ``None`` for them (a bare ``Name`` / a ``Call`` is "not statically
certain"). This objective fills exactly that gap, lands types nothing else can, and
stays an honest under-claim everywhere else.

The inference + plan live in
:mod:`app.execution.semantic.transforms.type_annotations`
(``plan_annotate_self_returns``, which threads the enclosing-class name and the
module's top-level bound names into the shared ``infer_annotations`` engine — see
``_infer_self_return_type``); this module only names it as a develop objective and
registers itself with the develop registry. Standard module-objective shape (one
``plan_fn`` per own module), so it reuses ``_base.register_module_objective`` — the
same suite-gated, auto-rollback develop loop as every other objective, and the plan
layer refuses test/fixture files.

The single write is behaviour-IDENTICAL (a string return annotation is never
evaluated at runtime and changes no value), and the FULL refusal set lives with the
engine: not inside exactly one resolvable enclosing ``ClassDef``; any value-return
not ``self`` (resp. not ``cls(...)``); ``cls(...)`` outside ``@classmethod``;
``self``/``cls`` reassigned in the body; already annotated; a generator; a
non-terminating body; a bare-``return`` mix; ``@staticmethod``/``@property``; a
test/fixture/non-library file; non-parsing source. Deterministic, stdlib-only,
zero-token, offline.
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.semantic.transforms.type_annotations import (
    plan_annotate_self_returns,
)

register_module_objective(
    "annotate-self-returns", plan_annotate_self_returns,
    operator="annotate_self_returns",
    description="add provable self/cls forward-ref return types in {rel}",
)
