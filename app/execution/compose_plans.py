"""Compose two single-file plans into ONE multi-file atomic plan.

Apex's concrete objectives each land a change to exactly ONE module's
``new_contents`` (implement a stub in A, wire an export in B's ``__init__.py``,
…). The gated writer already spans N files — :func:`apply_rename` writes every
entry in ``new_contents``, gates the whole set ONCE, and rolls back ALL of them
(restoring originals, deleting created files) byte-for-byte on any regression.
The missing piece is purely PLAN CONSTRUCTION: nothing merges two single-file
plans into one multi-file :class:`RenamePlan`.

:func:`compose_plans` is that merge — a pure, stdlib-only, IO-free, AST-free
UNION of two plans' ``new_contents``/``originals``/``edits_by_file`` (plus their
scope hints), so the EXISTING engine lands them as one atomic, once-gated,
unit-rolled-back change. It is a COMPOSITION PRIMITIVE, not a develop objective:
it registers nothing and NEVER calls :func:`apply_rename` (the single-gated-writer
contract is preserved — the merged plan still flows through the one legal call
site in ``objective_compiler``).

Conservative by design — it REFUSES (returns a plan whose ``.blockers`` make
``.ok`` False, landing nothing) rather than guess when:
  - either sub-plan already has blockers (a refusal can't be composed away);
  - either sub-plan is empty (a no-op has nothing provable to contribute);
  - the two plans' ``new_contents`` share ANY file — the key soundness gate: two
    plans editing the same file would each clobber the other's bytes, so the
    union is ill-defined and the composition refuses.

:func:`compose_chain` folds that pairwise merge over a WHOLE LIST of plans: a
left fold that grows one accumulated multi-file plan and re-runs :func:`compose_plans`
against it at every step. Because the accumulator carries the running UNION of
every file merged so far, ``compose_plans``' own overlap guard now checks each new
plan against the ENTIRE accumulated set — so the N-way merge REFUSES the moment
ANY two plans in the list touch the same file, never a silent clobber. The soundness
carries over VERBATIM: the fold only composes plans (it never writes a file, never
calls :func:`apply_rename`), so the merged plan still flows through the ONE legal
gated writer, gated once and unit-rolled-back.

Deterministic (a pure dict-merge with ``sorted`` on the list fields — no clock,
no randomness), zero-token, idempotent in shape.
"""

from __future__ import annotations

from app.execution.cross_file_rename import RenamePlan


def _refusal(reason: str) -> RenamePlan:
    """A composed plan that lands NOTHING: ``.blockers`` is set (so ``.ok`` is
    False) and ``new_contents`` stays empty. Mirrors the existing refusal style —
    the reason rides the plan's blockers channel the engine already renders."""
    plan = RenamePlan(old="compose", new="compose")
    plan.blockers.append(reason)
    return plan


def compose_plans(a: RenamePlan, b: RenamePlan) -> RenamePlan:
    """Merge two single-file plans into ONE multi-file :class:`RenamePlan`.

    On success the merged plan is the UNION of ``a`` and ``b``: ``new_contents``,
    ``originals`` and ``edits_by_file`` are ``{**a, **b}`` (keys provably disjoint
    after the overlap guard), so :func:`apply_rename` writes both files, gates the
    whole set ONCE, and rolls them back as a unit on any regression. The list
    fields are sorted unions so the result is byte-stable across runs.

    Refuses (lands nothing) when either sub-plan has blockers, either is empty, or
    the two plans touch the SAME file — see the module docstring. Pure, IO-free,
    AST-free, deterministic."""
    if a.blockers or b.blockers:
        return _refusal("a sub-plan already refused — cannot compose a blocked plan")
    if not a.new_contents or not b.new_contents:
        return _refusal("a sub-plan is empty — nothing provable to compose")
    overlap = sorted(set(a.new_contents) & set(b.new_contents))
    if overlap:
        return _refusal(
            f"plans conflict on the same file(s) {overlap} — refusing to compose")

    merged = RenamePlan(old=f"{a.old}+{b.old}", new="compose")
    merged.new_contents = {**a.new_contents, **b.new_contents}
    merged.originals = {**a.originals, **b.originals}
    merged.edits_by_file = {**a.edits_by_file, **b.edits_by_file}
    merged.derived_from = sorted(set(a.derived_from) | set(b.derived_from))
    # Union the per-symbol pinned nodes both fills make green, then deselect only
    # the pre-existing-red sibling nodes NEITHER side needs — preserving the
    # never-deselect-a-needed-node invariant (implement_stub.py:151): a node a
    # filled stub (on EITHER side) depends on must keep running, so subtract the
    # merged included set from the merged excluded set. Sorted/deterministic.
    included = set(a.scoped_test_nodes) | set(b.scoped_test_nodes)
    excluded = set(a.scoped_excluded_nodes) | set(b.scoped_excluded_nodes)
    merged.scoped_test_nodes = sorted(included)
    merged.scoped_excluded_nodes = sorted(excluded - included)
    merged.warnings = a.warnings + b.warnings
    return merged


def compose_chain(plans: list[RenamePlan]) -> RenamePlan:
    """LEFT-FOLD the pairwise :func:`compose_plans` over ``plans`` — merge a whole
    whole-file-DISJOINT set of single-file plans into ONE multi-file atomic plan.

    The canonical N-way coordinated change a team writes by hand: implement a stub
    in module A, wire its export in package B, infer hints in module C — each a
    single-file plan today. This folds them into ONE :class:`RenamePlan` so
    :func:`apply_rename` writes the whole set, gates it ONCE, and rolls every file
    back as a unit on any regression.

    The fold grows one ACCUMULATED plan and re-runs :func:`compose_plans` against it
    at each step. Since the accumulator carries the running UNION of every file
    merged so far, ``compose_plans``' existing overlap guard checks each next plan
    against the ENTIRE accumulated union — so the merge REFUSES (returns a blocked
    plan that lands nothing) the moment ANY two plans in the list share a file, and
    equally when any sub-plan is blocked or empty. The refusal is ``compose_plans``'
    verbatim (never a new gate, never a silent clobber); the fold merely HONORS it,
    returning the blocked plan as soon as one appears rather than forcing a
    conflicting merge.

    Refuses a list of FEWER THAN TWO plans: a chain needs at least two plans to
    compose (a lone plan is not a merge — the caller should land it directly).
    Pure, IO-free, AST-free, deterministic — the same list yields a byte-identical
    plan, and it NEVER calls :func:`apply_rename` (the single-gated-writer contract
    is preserved: the merged plan flows through the one legal call site)."""
    if len(plans) < 2:
        return _refusal(
            "compose_chain needs at least two plans to merge — nothing to compose")
    merged = plans[0]
    for plan in plans[1:]:
        merged = compose_plans(merged, plan)
        if merged.blockers:
            return merged  # honor the refusal — overlap / blocked / empty sub-plan
    return merged
