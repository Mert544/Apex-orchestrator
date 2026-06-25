"""complete-match-exhaustiveness develop objective — fill the missing arm of a
dispatch over a PROVABLY-CLOSED discriminant set with a LOUD exhaustiveness sentinel.

A ``match``/``case`` block or an ``if``/``elif`` chain over a discriminant whose value
set is provably closed (an ``Enum`` subclass defined in THIS module, a ``Literal[...]``
of simple constants, or ``bool``) but missing a member arm AND carrying no catch-all
has a SILENT fall-through — a latent bug. This objective LANDS one final
``case _:`` / trailing ``else:`` whose body is
``raise AssertionError(f"unhandled <subject>: {<subject>!r}")``, turning the silent
miss LOUD. The dispatch-level sibling of enforce-enum-unique.

SOUNDNESS is STRUCTURAL, not suite-as-correctness: the inserted arm executes ONLY on a
discriminant value the existing code does not handle today — so it is either dead code
(the value can't occur → behaviour-preserving) or it makes a pre-existing silent
fall-through loud (an improvement). In both cases NO currently-passing test can
regress (the runtime-additive posture of @enum.unique). REFUSE (an honest no-op) on
every uncertainty — a discriminant not provably closed (a bare ``str``/``int``, a
non-literal ``Literal``, an enum imported/aliased from another module), a
wildcard/capture/trailing-``else`` already present (already total), an unmodelled match
subject, a guarded/unmappable arm. apply_rename's full-suite gate + auto-rollback are
the backstop.

The detection + minimal rewrite live in :mod:`app.execution.match_exhaustiveness`
(``complete_match_exhaustiveness``); this module only names it as a develop objective
and self-registers. Standard single-file shape — no whole-project scan is needed (the
closed-set proof is purely intra-module), so it reuses ``plan_source_rewrite``
directly, which already refuses test/fixture and non-library files and captures the
original for rollback. This module NEVER writes the project tree itself (the
soundness_audit S1 single-gated-writer assertion forbids it; a pure transform satisfies
it). Deterministic (pure AST walk + reverse-order line splice, no clock/random/
hashseed), stdlib-only, zero-token, idempotent (a second run sees the sentinel arm and
is a byte-identical no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.match_exhaustiveness import complete_match_exhaustiveness
from app.execution.objectives._base import register_module_objective


def plan_complete_match_exhaustiveness(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the complete-match-exhaustiveness plan for one module, or an honest no-op.

    Delegates to the shared single-file ``plan_source_rewrite`` (refuse test/fixture
    and non-library files, read, run ``complete_match_exhaustiveness``, record the one
    in-place rewrite with its original so the verified-apply engine can roll it back).
    An empty plan means nothing to do here — no fillable closed-set dispatch, or the
    module does not parse — a no-op, not a failure."""
    return plan_source_rewrite(
        project_root, module_rel, "complete_match_exhaustiveness",
        complete_match_exhaustiveness)


register_module_objective(
    "complete-match-exhaustiveness", plan_complete_match_exhaustiveness,
    operator="complete_match_exhaustiveness",
    description="add a loud exhaustiveness sentinel to a closed-set dispatch in {rel}",
)
