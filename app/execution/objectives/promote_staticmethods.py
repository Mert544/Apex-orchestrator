"""Self-registering objective: promote-staticmethod.

Promote a class's SELF-FREE methods (those that never touch ``self``) to
``@staticmethod`` — a behaviour-preserving DECOUPLING step that makes the
coupling surface honest WITHOUT changing any call site (a ``@staticmethod`` is
still a class attribute, so ``self.m()`` / ``Cls.m()`` / ``inst.m()`` all keep
resolving; only the signature loses its now-unused ``self``). This REDUCES a
class's coupling but does NOT reduce its method count or split responsibilities —
the full decomposition stays a DESIGN task — so it is a PARTIAL, honest first
step on a method-bag god-class.

The detection + minimal splice live in :mod:`app.execution.promote_staticmethods`
(``plan_promote_staticmethods``); this module only names it as a develop objective
and registers itself with the develop registry, so it becomes a first-class
`apex develop --objective promote-staticmethod` (and shows up in `apex plan` /
`apex ascend`) with no hub edit.

The refusal set is the safety oracle (refuse ⇒ an honest no-op): a method that
uses ``self``, is already ``@staticmethod`` / ``@classmethod``, carries ANY other
decorator, is a dunder, does not lead with ``self``, uses ``super``, whose NAME is
defined by >1 class (a possible override / MRO participant), whose class is not
top-level, or whose NAME appears as a bare string literal anywhere in the repo (a
dynamic ``getattr`` / ``__all__`` / monkeypatch target) is REFUSED — plus the
standard test/fixture and non-library-script file refusals. It is a TIDY,
behaviour-preserving structural refactor (like its neighbours extract-guard-clause
/ dedup-parameterized), so it takes the default ``ObjectiveSpec`` flags
(full-suite gate, no impact-scoping). Deterministic (pure AST walk + line splice,
candidates in source order, no clock/random), stdlib-only, zero-token, idempotent
(a second run sees the ``@staticmethod`` it landed and refuses — a byte-identical
no-op).
"""

from __future__ import annotations

from app.execution.objectives._base import register_module_objective
from app.execution.promote_staticmethods import plan_promote_staticmethods

register_module_objective(
    "promote-staticmethod", plan_promote_staticmethods,
    operator="promote_staticmethod",
    description="promote self-free methods to @staticmethod in {rel}",
)
