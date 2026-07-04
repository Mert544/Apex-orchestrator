"""Near-Dup Guarded-Return — lift a GUARD-RETURN near-duplicate group into ONE
parameterized helper, via sentinel projection.

The near-dup family's control-flow ladder gains its THIRD (and final) rung,
completing the parameterized x {plain, total, guarded} matrix:
:mod:`app.execution.near_dup_extract` (``dedup-parameterized``) lifts a
near-duplicate group whose block is a plain run or a clean single TAIL
``return``; :mod:`app.execution.near_dup_total_return`
(``dedup-parameterized-total-return``) lifts the ALWAYS-RETURNING complement
— every exit path returns/raises. This module lifts the REMAINING shape both
refuse: a near-duplicate group whose block has a guard ``return`` on SOME
path AND a live fall-through — :mod:`app.execution.dedup_guarded_return`'s own
admissible shape (the exact-dup sibling), now parameterized.

SHARE IN PLACE, MOVE NOTHING: this module is a thin RESOLVER plugged into
:mod:`app.execution.near_dup_extract`'s shared ``_match_parameterized``
matcher (occurrence parsing, module reads, the full family soundness rails,
the structural-template/leaf-path/diff-count re-verification, the
Constant-only value-hole gates) — every rail near_dup_extract enforces
applies here for free, at zero duplication cost. Only the occurrence
RESOLUTION differs (delegated VERBATIM to
:func:`app.execution.dedup_guarded_return._resolve_guarded_return` — the
guard-return admissibility shape, the W100 definite-assignment rail, and the
(W99b-fix) live-in bound-before-run rail all apply unchanged), and the EMIT is
:mod:`app.execution.dedup_guarded_return`'s sentinel-projection scheme
(``_call_lines``/``_emit_file``/``_emit_all_files``/``_free_sentinel_name``,
each generalized with a default-preserving keyword — share in place, nothing
duplicated) widened by the hole params instead of a single call line.

ROUTING (disjoint by construction, so the three near-dup lanes never contend
for the same group): NO explicit routing gate is needed here (unlike the
total-return sibling's own ``_block_reason`` check) — a clean tail-return run
ALWAYS returns, so ``_guarded_return_reason``'s own always-returns check
refuses it as "dedup-total-return's job"; a plain run has no return at all,
so the same function refuses it as "dedup_extract's job". The three
admissible shapes are intrinsically disjoint complements — probe-confirmed
live (a natural guarded fixture's shifted always-return window is refused
here with exactly that blocker, while the SAME window lands under
``plan_near_dup_total_return``).

Every other rail is inherited for free through the shared matcher: the
pattern/f-string/annotation/Constant-only/single-line hole gates, the
hole-overlap splice guard, the widened ``p<n>`` seed, occurrence-span
overlap, cross-module free-global rebinds, the per-run rails (async blocks,
multi-line string/bytes/f-string constants, reflection, pre-run closures,
invisible non-``Name`` bindings, ``global``/``nonlocal``-declared names, and
a ``class`` statement anywhere in the run), docstring-position runs,
structural template drift, the leaf-path/diff-count/detector
re-verification, and (W99b-fix) the live-in bound-before-run rail. Plus the
guarded-return lane's OWN emit-side rails: the shadowed-builtin check
(``object``/``type``/``tuple``/``len`` must resolve to the real builtins),
sentinel freeness (now extended over the hole ``p<n>`` params too), and rvar
freeness. PER-OCCURRENCE checks stay load-bearing throughout.

Deterministic, stdlib-only; no time, randomness, network, or identity
strings.
"""

from __future__ import annotations

from pathlib import Path

from app.execution._dedup_helpers import stamp_multi_module_plan
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import _Occurrence, _module_dotted
from app.execution.dedup_guarded_return import (
    _Emit,
    _emit_all_files,
    _free_result_name,
    _free_sentinel_name,
    _names_tuple,
    _resolve_guarded_return,
    _shadowed_emit_builtin,
)
from app.execution.dedup_total_return import _choose_helper_name
from app.execution.extract_method import _reindent
from app.execution.near_dup_extract import (
    _hole_params,
    _match_parameterized,
    _segment,
    _splice_first,
)

__all__ = ["plan_near_dup_guarded_return"]


def _resolve_parameterized_guarded_return(
    root: Path, rel: str, start_line: int, n_statements: int,
    sources: dict, trees: dict, plan: RenamePlan,
) -> _Occurrence | None:
    """Resolve one ``module:lineno`` occurrence into an :class:`_Occurrence`
    for a GUARD-RETURN near-dup block. A one-line delegate to
    :func:`app.execution.dedup_guarded_return._resolve_guarded_return` — the
    SAME control-flow admissibility (a run with a ``return`` on some path
    that does NOT always-return), the SAME W100 definite-assignment rail for
    live-out names, and the SAME (W99b-fix) live-in bound-before-run rail,
    all inherited verbatim. ``root`` is unused, kept for signature symmetry
    with :func:`app.execution.dedup_extract._resolve_occurrence` (the calling
    convention :func:`app.execution.near_dup_extract._resolve_all_occurrences`
    establishes; precedent: ``near_dup_total_return
    ._resolve_parameterized_total_return``)."""
    return _resolve_guarded_return(rel, start_line, n_statements, sources,
                                   trees, plan)


def _build_parameterized_guarded_helper(
    first: _Occurrence, helper_name: str, live_in: list, param_names: list,
    sentinel: str, live_out: list, diff_cols: list, leaves: list,
    plan: RenamePlan,
) -> str | None:
    """The parameterized mirror of ``dedup_guarded_return._build_guarded_helper``:
    the block SPLICED (each differing constant replaced by its parameter
    name, by source span — :func:`app.execution.near_dup_extract
    ._splice_first`) instead of lifted verbatim, and the signature widened by
    the hole params. Returns the assembled ``sentinel = object()`` + ``def``
    block text, or ``None`` (recording a blocker) if a hole can't be
    unambiguously spliced."""
    body_text = _splice_first(first, diff_cols, leaves, param_names, plan)
    if body_text is None:
        return None
    base_indent = (len(first.lines[first.span_lo - 1])
                   - len(first.lines[first.span_lo - 1].lstrip()))
    body_lines = _reindent(body_text.splitlines(keepends=True), base_indent)
    if live_out:
        tail = f"    return ({sentinel}, ({_names_tuple(live_out)}))"
    else:
        tail = f"    return {sentinel}"
    sig = ", ".join(list(live_in) + param_names)
    src = [f"{sentinel} = object()", "", "",
           f"def {helper_name}({sig}):"] + body_lines + [tail]
    return "\n".join(src) + "\n\n\n"


def _const_args_of(resolved: list, per_occ_leaves: list, diff_cols: list):
    """A ``const_args_of`` callback for :func:`_emit_all_files`: each
    occurrence's OWN per-column constant literals, in column order — the same
    per-occurrence extraction :func:`app.execution.near_dup_extract
    ._rewrite_call_sites` performs for the plain/total-return lanes."""
    index_of = {id(occ): i for i, occ in enumerate(resolved)}

    def _for_occ(occ: _Occurrence) -> tuple:
        i = index_of[id(occ)]
        return tuple(_segment(occ.source, per_occ_leaves[i][col][1])
                    for col in diff_cols)

    return _for_occ


def plan_near_dup_guarded_return(project_root: str | Path, group) -> RenamePlan:
    """Plan lifting a GUARD-RETURN near-duplicate ``group`` into one
    parameterized helper via sentinel projection.

    ``group`` is a :class:`~app.engine.near_dup.NearDuplicateGroup` — the
    same shape :func:`app.execution.near_dup_extract.plan_near_dup_extract`
    and :func:`app.execution.near_dup_total_return.plan_near_dup_total_return`
    consume. This planner accepts ONLY the guard-return complement both
    siblings refuse — a block with a ``return`` on some path AND a reachable
    fall-through — and parameterizes it via the SAME shared matcher
    (Constant-only value holes, the full family soundness rails) plus the
    guarded-return lane's own sentinel-projection emit. Returns a
    :class:`RenamePlan` ready for ``apply_rename`` (suite-verified,
    auto-rollback). On the slightest doubt the plan carries a blocker and
    empty ``new_contents`` — correctness and safety over coverage.
    """
    plan = RenamePlan(old="near_dup_guarded_return", new="_shared")
    root = Path(project_root)

    matched = _match_parameterized(
        root, group, plan, resolver=_resolve_parameterized_guarded_return)
    if matched is None:
        return plan
    (sources, trees, rels, resolved, live_in, live_out, _tail_return,
     per_occ_leaves, diff_cols) = matched

    # Guarded-return's own emit-side rail: the emitted `object()`/`type`/
    # `tuple`/`len` must resolve to the real builtins everywhere.
    shadow = _shadowed_emit_builtin(resolved, trees, rels)
    if shadow is not None:
        plan.blockers.append(shadow)
        return plan

    helper_name = _choose_helper_name(resolved, trees, rels, plan)
    if helper_name is None:
        return plan

    first = resolved[0]
    # Constant leaves always fail `_hole_param_names`' all-`ast.Name` check,
    # so the descriptive branch never fires today — always `p<n>` (the H-B
    # closure seed still guards against a run-bound `p0`).
    param_names = _hole_params(resolved, per_occ_leaves, diff_cols, first,
                               live_in, live_out)

    # The sentinel is referenced in the helper's tail where the p<n> params
    # are in scope; a same-named param would shadow it. Unreachable today
    # (`p\d+` never collides with `_UPPER_MISS`), but W99c's descriptive
    # Name-hole names make it reachable — the rail is wired now regardless.
    sentinel = _free_sentinel_name(helper_name, trees, set(rels), resolved,
                                   also_avoid=frozenset(param_names))
    if sentinel is None:
        plan.blockers.append("could not find a free module-level sentinel name")
        return plan

    rvar = _free_result_name(resolved)
    if rvar is None:
        plan.blockers.append(
            "could not find a free result name in the enclosing functions")
        return plan

    helper_block = _build_parameterized_guarded_helper(
        first, helper_name, live_in, param_names, sentinel, live_out,
        diff_cols, per_occ_leaves[0], plan)
    if helper_block is None:
        return plan

    emit = _Emit(
        helper_name=helper_name, helper_block=helper_block, rvar=rvar,
        sentinel=sentinel, live_in=tuple(live_in), live_out=tuple(live_out),
        first_rel=first.rel, first_container=first.container,
        first_dotted=_module_dotted(first.rel),
    )
    emitted = _emit_all_files(
        resolved, sources, trees, emit, plan,
        const_args_of=_const_args_of(resolved, per_occ_leaves, diff_cols))
    if emitted is None:
        return plan
    new_contents, edits = emitted

    stamp_multi_module_plan(plan, emit.helper_name, first.rel, sources,
                            new_contents, edits)
    # Omit the exact lane's zero-param warning: `diff_count >= 1`
    # (near_dup_extract._validate_group_shape) guarantees >= 1 hole param, so
    # the helper is never parameterless here — unreachable by construction.
    return plan
