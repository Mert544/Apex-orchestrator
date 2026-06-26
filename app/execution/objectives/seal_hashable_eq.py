"""Self-registering objective: seal-hashable-eq.

Restore the canonical field-based ``__hash__`` on a project's own regular
(non-``@dataclass``) class that defines ``__eq__`` in its OWN body but does NOT
define ``__hash__`` and is NOT already deliberately unhashable. THE PYTHON RULE:
defining ``__eq__`` sets ``__hash__ = None`` implicitly, making instances
UNHASHABLE (``TypeError: unhashable type`` in a ``set`` / ``dict`` key) — authors
routinely forget to restore the ``__hash__`` that pairs with their ``__eq__``. This
lands the canonical ``def __hash__(self): return hash((self.f1, self.f2, ...))``
over the SAME proven pure-copy field set ``synthesize_dunders`` already trusts,
RESTORING set/dict-key usability: a real landed capability (instances become
dict-key / set usable where they currently raise at runtime), not advice — the
``__hash__`` sibling of synthesize-dunders.

The detection + minimal splice live in :mod:`app.execution.hashable_eq`
(``seal_hashable_eq``); this module only names it as a develop objective and
registers itself. Standard single-file shape — NO whole-project scan is needed (the
proof is PURELY INTRA-MODULE: a single class's own body proves a body-``__eq__`` is
present, ``__hash__`` is absent, and the field set is its own ``__init__`` copy set;
there is no base, so there is no inherited-hash contract to resolve, UNLIKE
synthesize-dunders whose inherited-``__eq__`` contract needs a project-own scan) — so
it reuses ``plan_source_rewrite`` directly. This makes it strictly simpler / safer
than synthesize-dunders.

NOT expensive and NOT scope_verify — the in-process AST gate is cheap, and the lone
residual (a field whose own value is itself unhashable, so hashing an instance
raises) is a RUNTIME mismatch the FULL default suite gate catches (and
``apply_rename`` byte-rolls-back), so it takes the default ``ObjectiveSpec`` flags
(full-suite gate, no impact-scoping). The transform refuses (a no-op) a module with
no eligible class: no body-``__eq__`` (an inherited ``__eq__`` is not provably
present); an already-present ``__hash__`` (a ``def`` OR any binding, incl.
``__hash__ = None`` — a deliberate unhashable choice); an ``@dataclass``-decorated
class; a base other than ``object`` (an Enum / Protocol / ABC subclass, or any
inherited-hash contract); a non-enumerable / empty pure-copy field set; an
``__eq__`` bound by assignment / lambda rather than ``def``; or unparseable source.
Deterministic (pure AST walk + line splice, no clock/random), stdlib-only,
zero-token, idempotent (a second run sees the ``__hash__`` it landed and is a
byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.hashable_eq import seal_hashable_eq
from app.execution.objectives._base import register_module_objective


def plan_seal_hashable_eq(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the seal-hashable-eq plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse test/fixture,
    read, run ``seal_hashable_eq``, record the one in-place rewrite with its original
    so the verified-apply engine can roll it back). An empty plan means nothing to do
    here — no eligible class, or the module does not parse — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "seal_hashable_eq",
        seal_hashable_eq)


register_module_objective(
    "seal-hashable-eq", plan_seal_hashable_eq,
    operator="seal_hashable_eq",
    description="restore the canonical __hash__ over the eq fields of a class in {rel}",
)
