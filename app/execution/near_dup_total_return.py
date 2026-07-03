"""Near-Dup Total-Return — lift an ALWAYS-RETURNING near-duplicate group into
ONE parameterized returning helper.

The near-dup family's control-flow ladder gains its second rung. The base
:mod:`app.execution.near_dup_extract` (``dedup-parameterized``) lifts a
near-duplicate group whose block is a plain run or a single TAIL ``return`` —
the same admissible shape :mod:`app.execution.dedup_extract` accepts for
exact duplicates. This module lifts the complement: a near-duplicate group
whose block is TOTAL-RETURN (:func:`app.execution.dedup_total_return
._always_returns` — every exit path returns/raises: a guard ``return`` on
some path plus a final ``return``, or an ``if``/``elif``/``else`` ladder
where every branch returns) — the shape dedup-parameterized refuses because
it isn't a clean single tail return.

Because the block ALWAYS returns, everything after it in the enclosing
function is unreachable, so ``live_out`` is hardcoded ``[]`` (the same
precedent :mod:`app.execution.dedup_total_return` sets for the exact-dup
sibling) — the block's own ``return`` propagates the value, and each copy
becomes ``return {helper}(<live_in>, <its own constant args>)``.

SHARE IN PLACE, MOVE NOTHING: this module is a thin RESOLVER plugged into
:mod:`app.execution.near_dup_extract`'s shared ``_plan_parameterized``
pipeline (occurrence parsing, module reads, the Constant-only value-hole
gates, the full family soundness rails, helper build, call-site/import
rewrites, gate-clean imports, the finalise stamp) — every rail and gate
near_dup_extract enforces applies here for free, at zero duplication cost.
Only the occurrence RESOLUTION differs: admissibility is TOTAL-RETURN
(:func:`app.execution.dedup_total_return._total_return_reason`, imported
VERBATIM) rather than plain/tail-return, and ``live_out`` is always ``[]``.

ROUTING COMPLEMENT (disjoint by construction, so the two near-dup lanes never
contend for the same group): a block :func:`app.execution.dedup_extract
._block_reason` admits (``None`` reason — a plain block or a clean single
tail return) is refused HERE first, routed back to dedup-parameterized's job.

Every other rail is inherited for free through the shared pipeline: the
pattern/f-string/annotation/Constant-only/single-line hole gates, the
hole-overlap splice guard, the widened ``p<n>`` seed, occurrence-span
overlap, cross-module free-global rebinds, the per-run rails (async blocks,
multi-line string/bytes/f-string constants, reflection, pre-run closures,
invisible non-``Name`` bindings, ``global``/``nonlocal``-declared names, and
a ``class`` statement anywhere in the run), docstring-position runs,
structural template drift, and the leaf-path/diff-count/detector
re-verification. PER-OCCURRENCE checks stay load-bearing throughout.

Deterministic, stdlib-only; no time, randomness, network, or identity
strings.
"""

from __future__ import annotations

from pathlib import Path

from app.execution._dedup_helpers import resolve_occurrence_prefix
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import _Occurrence, _block_reason, _locate_run
from app.execution.dedup_total_return import (
    _total_return_occurrence,
    _total_return_reason,
)
from app.execution.near_dup_extract import _plan_parameterized

__all__ = ["plan_near_dup_total_return"]


def _resolve_parameterized_total_return(
    root: Path, rel: str, start_line: int, n_statements: int,
    sources: dict, trees: dict, plan: RenamePlan,
) -> _Occurrence | None:
    """Resolve one ``module:lineno`` occurrence into an :class:`_Occurrence`
    for an ALWAYS-RETURNING near-dup block. Same ``resolver(root, rel, line,
    n_statements, sources, trees, plan)`` shape
    :func:`app.execution.near_dup_extract._resolve_all_occurrences` calls for
    every resolver (``root`` is unused, kept for signature symmetry with
    ``_resolve_occurrence`` — precedent: ``dedup_total_return._resolve_all``).
    Records a blocker and returns ``None`` on any unsafe, ambiguous, or
    wrongly-routed case."""
    prefix = resolve_occurrence_prefix(plan, rel, start_line, n_statements,
                                       sources, trees, _locate_run)
    if prefix is None:
        return None
    source, fn, container, run = prefix

    # Routing complement FIRST: a plain block or a clean single tail return
    # is dedup-parameterized's job, not ours — disjoint by construction, so
    # the two near-dup lanes never contend for the same group.
    if _block_reason(run)[0] is None:
        plan.blockers.append(
            f"{rel}:{start_line}: the range is a plain/tail-return block — "
            "that is dedup-parameterized's job, not a parameterized "
            "total-return lift")
        return None

    reason = _total_return_reason(run)
    if reason:
        plan.blockers.append(f"{rel}:{start_line}: {reason}")
        return None

    # Same admitted-run tail dedup_total_return's own resolver uses (shared,
    # not duplicated — see _total_return_occurrence's docstring).
    return _total_return_occurrence(rel, source, fn, container, run)


def plan_near_dup_total_return(project_root: str | Path, group) -> RenamePlan:
    """Plan lifting an ALWAYS-RETURNING near-duplicate ``group`` into one
    parameterized returning helper.

    ``group`` is a :class:`~app.engine.near_dup.NearDuplicateGroup` — the
    same shape :func:`app.execution.near_dup_extract.plan_near_dup_extract`
    consumes. This planner accepts ONLY the total-return complement its
    sibling refuses — a block whose EVERY exit path returns/raises — and
    parameterizes it via the SAME shared pipeline (Constant-only value holes,
    the full family soundness rails). Returns a :class:`RenamePlan` ready for
    ``apply_rename`` (suite-verified, auto-rollback). On the slightest doubt
    the plan carries a blocker and empty ``new_contents`` — correctness and
    safety over coverage."""
    return _plan_parameterized(project_root, group,
                               resolver=_resolve_parameterized_total_return,
                               plan_label="near_dup_total_return")
