"""Self-registering objective: seal-total-ordering.

Land ``@functools.total_ordering`` on a project's own regular class that defines
``__eq__`` AND EXACTLY ONE of the ordering dunders ``__lt__`` / ``__le__`` / ``__gt__``
/ ``__ge__`` but is MISSING the other three — the stdlib boilerplate-killer that fills
the three absent comparison operators from the one the author wrote plus ``__eq__``.
The comparison-dunder SIBLING of synthesize-dunders (which fills
``__repr__`` / ``__eq__`` / ``__hash__``): it lands real working code (``a <= b`` /
``a > b`` / ``a >= b`` start behaving consistently where they were previously absent →
``TypeError``), and ``@total_ordering`` never overwrites a method already defined, so
the change is RUNTIME-ADDITIVE. The honesty risk — landing it where the author intended
an asymmetric / partial comparison — is closed by the STATIC RAIL (refuse unless
``__eq__`` is defined in THIS class body AND exactly ONE order op is defined AND none of
the other three are) PLUS the suite gate + auto-rollback.

The detection + minimal splice live in :mod:`app.execution.total_ordering`
(``seal_total_ordering``); this module only names it as a develop objective and
registers itself. Standard single-file shape — no whole-project scan is needed (the
proof is purely intra-module: a single class's own body proves ``__eq__`` + exactly one
order op + the other three absent, UNLIKE synthesize-dunders whose inherited-``__eq__``
contract needs a project-own scan) — so it reuses ``plan_source_rewrite`` directly. The
transform refuses (a no-op) a module with no eligible class: no body-``__eq__`` (an
inherited ``__eq__`` is not provably present), zero / two-or-more / all-four order ops,
an already-``@total_ordering`` class, an order op or ``__eq__`` bound by assignment /
lambda, ``functools.total_ordering`` not provably spellable, an unmodelled class-body
binder, or unparseable source.

``functools.total_ordering`` exists since Python 3.2, so this lands on the 3.10 floor
with NO version gate. Deterministic (pure AST walk + line splice, no clock/random),
stdlib-only, zero-token, idempotent (a second run sees the ``@total_ordering`` it landed
and is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.objectives._base import register_module_objective
from app.execution.total_ordering import seal_total_ordering


def plan_seal_total_ordering(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the seal-total-ordering plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse test/fixture,
    read, run ``seal_total_ordering``, record the one in-place rewrite with its original
    so the verified-apply engine can roll it back). An empty plan means nothing to do
    here — no eligible class, or the module does not parse — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "seal_total_ordering",
        seal_total_ordering)


register_module_objective(
    "seal-total-ordering", plan_seal_total_ordering,
    operator="seal_total_ordering",
    description="add @functools.total_ordering to a single-order-op class in {rel}",
)
