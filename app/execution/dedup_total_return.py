"""Dedup Total-Return — lift an EXACT-duplicate block that always returns.

Diagnosing Apex's own near-duplicates showed that the single biggest remaining
"detect >> act" gap is control flow: a large share of duplicate groups are
blocked because the shared run contains a ``return`` that is **not** the simple
tail return :mod:`app.execution.dedup_extract` already handles (a guard
``return`` mid-block, an ``if/else`` where each branch returns, etc.).

This module handles ONE precisely-bounded, provably-safe subset of that gap: a
*total-return* block — a run of statements whose EVERY exit path is a ``return``
(or ``raise``), so control can never fall off its end. Concretely the run is
total-return when ``_always_returns`` holds:

  - the LAST statement is a ``return`` or ``raise``; OR
  - the LAST statement is an ``if`` (with ``elif``/``else`` chained) where the
    body AND the ``orelse`` each recursively always-return — an ``if`` with no
    ``else`` can fall through, so it is NOT total-return;
  - an EARLIER ``return``/``raise`` is fine (it's a guard); anything after a
    point that always-returns is simply unreachable.

Because such a block ALWAYS returns, anything after it in the enclosing function
is unreachable (``live_out`` is empty). The whole block — guards, branches, and
its final return, verbatim — lifts into ``def _shared_n(<live_in>): <block>`` and
each copy becomes ``return _shared_n(<live_in>)``.

Everything else is a **blocker**, by design: a return in the MIDDLE with
reachable code after it, a loop that can fall through, a block that ends in a
plain statement (that's dedup_extract's job), or any ``yield`` / ``await`` /
``global`` / ``nonlocal`` / nested ``def``/``lambda`` / escaping
``break``/``continue``. Correctness over coverage, absolutely.

REVIEW-ONLY scaffolding: this builds the transform and is intentionally NOT
registered as an objective and NOT wired into any flow. It consumes an
EXACT-duplicate :class:`~app.engine.dedup.DuplicateBlock` (the same input
dedup_extract takes), reusing dedup_extract's occurrence resolution, data-flow,
signature gate, helper build, call-site rewrite, and gate-clean imports by
import — only the control-flow admissibility rule is new here. Deterministic,
stdlib-only; produces a suite-verified :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._dedup_helpers import stamp_multi_module_plan
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import (
    _Occurrence,
    _descriptive_helper_name,
    _free_helper_name,
    _import_insert_index,
    _locate_run,
    _module_dotted,
    _parse_occurrence,
)
from app.execution.extract_method import (
    _NESTED_SCOPE_NODES,
    _data_flow,
    _enclosing_function,
    _has_unenclosed_jump,
    _reindent,
)
from app.execution.unused_imports import strip_unused_imports

__all__ = ["plan_dedup_total_return", "_always_returns"]

# Statements that on their own divert control away from "fall off the end":
# ``return`` and ``raise`` both guarantee the enclosing run does not continue.
_TERMINATORS = (ast.Return, ast.Raise)

# Nodes that, anywhere in the run, would change control-flow semantics if the
# run were relocated into a helper (or that this pass deliberately won't analyze).
_FLOW_HAZARDS = (ast.Yield, ast.YieldFrom, ast.Await, ast.Global, ast.Nonlocal)


def _always_returns(stmts: list) -> bool:
    """True iff control can NEVER fall off the end of ``stmts`` — every exit path
    terminates in a ``return`` (or ``raise``).

    The rule, applied to the LAST statement of the run (earlier statements are
    irrelevant: if the tail always-returns, the block always-returns, and any
    code after an earlier always-returning point is unreachable):

      - empty run               → False (it falls straight through);
      - last is return/raise    → True;
      - last is an ``if``       → True iff its body AND its ``orelse`` each
                                  recursively ``_always_returns`` (so an ``if``
                                  with NO ``else`` is False — it can fall
                                  through; an ``if/elif/else`` recurses because
                                  ``elif`` is just a nested ``if`` in ``orelse``);
      - anything else (loop,
        assignment, with, try,
        plain expr, ...)        → False — it can fall through.

    Loops are deliberately treated as fall-through even when their body returns:
    a zero-iteration loop falls off its end, so a loop tail is never total-return
    here. ``with``/``try`` are likewise conservatively fall-through. This keeps
    the admissible set provably safe rather than maximal.
    """
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, _TERMINATORS):
        return True
    if isinstance(last, ast.If):
        # An ``if`` is total-return only when it definitely takes one of two
        # branches that each always-return; no ``orelse`` means it may fall
        # through. ``elif`` chains live inside ``orelse`` as a nested ``If``,
        # so the recursion covers the whole if/elif/else ladder.
        if not last.orelse:
            return False
        return _always_returns(last.body) and _always_returns(last.orelse)
    return False


def _total_return_reason(run: list) -> str | None:
    """The reason ``run`` is NOT a safe total-return block to lift, or ``None``
    when it is. Mirrors dedup_extract's hazard set, but the admissibility shape
    is "always returns" (via :func:`_always_returns`) rather than "tail return".

    Blocks for: a nested ``def``/``lambda`` (unanalyzable scope); any
    ``yield``/``await``/``global``/``nonlocal`` (relocating changes control
    flow); an escaping ``break``/``continue`` (its loop is outside the run); and,
    finally, any run that does NOT always return — that's either dedup_extract's
    plain-block job or a genuinely non-total-return shape (a mid-block return
    with reachable code after, a fall-through loop, ...)."""
    for stmt in run:
        for n in ast.walk(stmt):
            if isinstance(n, _NESTED_SCOPE_NODES):
                return ("the range defines a nested function/lambda — its scope "
                        "can't be analyzed; extract it separately first")
            if isinstance(n, _FLOW_HAZARDS):
                return (f"the range contains `{type(n).__name__.lower()}` — moving "
                        "it into a helper would change control flow")
    if any(_has_unenclosed_jump(stmt) for stmt in run):
        return ("the range contains a `break`/`continue` whose loop is outside "
                "the selection — it can't be lifted out")
    if not _always_returns(run):
        return ("the range does not always return — control can fall off its end "
                "(a mid-block return with reachable code after, a fall-through "
                "loop, or a plain non-returning tail); not a total-return block")
    return None


def _resolve_total_return(rel: str, start_line: int, n_statements: int,
                          sources: dict, trees: dict,
                          plan: RenamePlan) -> _Occurrence | None:
    """Resolve one ``module:lineno`` occurrence into an :class:`_Occurrence` for a
    TOTAL-RETURN block, recording a blocker and returning ``None`` on any
    unsafe / ambiguous case. Same resolution shape as dedup_extract's
    ``_resolve_occurrence`` (reused helpers), differing only in the control-flow
    admissibility check (``_total_return_reason``)."""
    if rel not in trees:
        plan.blockers.append(f"{rel}: not a readable project module")
        return None
    tree = trees[rel]
    source = sources[rel]

    fn, container = _enclosing_function(tree, start_line, start_line)
    if fn is None:
        plan.blockers.append(
            f"{rel}:{start_line}: occurrence isn't inside one top-level "
            "function/method body (closures aren't supported)")
        return None

    run = _locate_run(fn, start_line, n_statements)
    if not run:
        plan.blockers.append(
            f"{rel}:{start_line}: couldn't snap the block to a contiguous run "
            f"of {n_statements} complete statements")
        return None

    reason = _total_return_reason(run)
    if reason:
        plan.blockers.append(f"{rel}:{start_line}: {reason}")
        return None

    before = fn.body[:fn.body.index(run[0])]
    after = fn.body[fn.body.index(run[-1]) + 1:]
    live_in, _live_out = _data_flow(fn, before, run, after)
    # The block unconditionally returns, so any fn-body statement after it is
    # unreachable — nothing flows out. The helper returns the value directly.
    live_out: list[str] = []

    span_lo = run[0].lineno
    span_hi = max(getattr(s, "end_lineno", s.lineno) for s in run)
    return _Occurrence(rel, source, source.splitlines(keepends=True), fn,
                       container, run, live_in, live_out, span_lo, span_hi,
                       True)  # tail_return=True: call site becomes `return helper(...)`


def _validate_block(block, plan: RenamePlan) -> tuple[list, int] | None:
    """Pull ``occurrences`` and statement count off ``block``, recording the
    relevant blocker and returning ``None`` when the block can't be a shared
    helper (fewer than two copies, or no statements)."""
    occurrences = list(getattr(block, "occurrences", []) or [])
    n_statements = int(getattr(block, "lines", 0) or 0)
    if len(occurrences) < 2:
        plan.blockers.append("a shared helper needs at least two occurrences")
        return None
    if n_statements < 1:
        plan.blockers.append("block has no statements to extract")
        return None
    return occurrences, n_statements


def _read_modules(root: Path, rels: list, plan: RenamePlan
                  ) -> tuple[dict, dict] | None:
    """Read & parse every involved module once (caller passes ``rels`` already
    sorted for deterministic order). Records a blocker and returns ``None`` on
    the first unreadable or unparseable module."""
    sources: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    for rel in rels:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            plan.blockers.append(f"cannot read {rel}")
            return None
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError as e:
            plan.blockers.append(f"{rel} doesn't parse: {e}")
            return None
        sources[rel] = text
    return sources, trees


def _signature_gate(resolved: list, plan: RenamePlan) -> tuple | None:
    """The shared helper has ONE interface: require an identical live-in signature
    across all copies (live_out is empty for every total-return block), else they
    aren't a clean shared helper. Returns the common ``(live_in, live_out)`` or
    ``None`` (with a blocker) on mismatch. Reuses dedup_extract's signature gate."""
    sig0 = (resolved[0].live_in, resolved[0].live_out)
    for occ in resolved[1:]:
        if (occ.live_in, occ.live_out) != sig0:
            plan.blockers.append(
                "occurrences have different data-flow signatures "
                f"(params/returns differ: {sig0} vs "
                f"{(occ.live_in, occ.live_out)}) — not a clean shared helper")
            return None
    return sig0


def _build_helper_block(first: _Occurrence, helper_name: str,
                        live_in: list) -> str:
    """Build the returning helper from the FIRST occurrence's real source. The
    block already contains its own returns, so NO trailing ``return`` is appended
    (live_out is empty) — we lift the run verbatim."""
    range_lines = first.lines[first.span_lo - 1:first.span_hi]
    base_indent = len(range_lines[0]) - len(range_lines[0].lstrip())
    body_lines = _reindent(range_lines, base_indent)
    helper_src = [f"def {helper_name}({', '.join(live_in)}):"] + body_lines
    return "\n".join(helper_src) + "\n\n\n"


def _emit_file(rel: str, occs: list, sources: dict, trees: dict,
               first: _Occurrence, first_dotted: str, helper_name: str,
               helper_block: str, call_line: str) -> tuple[str | None, str]:
    """Rewrite ONE module: replace each copy with ``return helper(...)`` (bottom-up
    so earlier spans stay valid), then either splice the helper def in (the file
    that defines it) or import it (any other file). Returns ``(new_source, "")``
    on success, or ``(None, blocker)`` if the emitted module would not parse."""
    lines = list(sources[rel].splitlines(keepends=True))

    # Replace each copy with a `return helper(...)`, bottom-up so earlier
    # spans stay valid.
    for occ in sorted(occs, key=lambda o: o.span_lo, reverse=True):
        indent = " " * (len(occ.lines[occ.span_lo - 1])
                        - len(occ.lines[occ.span_lo - 1].lstrip()))
        lines[occ.span_lo - 1:occ.span_hi] = [f"{indent}{call_line}"]

    if rel == first.rel:
        insert_at = _helper_insert_index(first.container, occs)
        lines[insert_at:insert_at] = [helper_block]
    else:
        # Another module: import the helper at the top (after __future__).
        import_line = f"from {first_dotted} import {helper_name}\n"
        lines.insert(_import_insert_index(trees[rel]), import_line)

    new_source = "".join(lines)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        return None, f"{rel}: extraction would not parse ({e})"

    # Gate-clean: lifting the block out can strand the imports it used, leaving
    # the emitted module with `F401 imported but unused`. Reuse the unused-import
    # detector on the NEW source and drop exactly those dead top-level imports;
    # the result is re-parse-checked inside that helper.
    cleaned = strip_unused_imports(new_source)
    return (new_source if cleaned is None else cleaned), ""


def _helper_insert_index(container, occs: list) -> int:
    """Index at which to splice the helper def: above the first occurrence's
    container. The anchor is an ORIGINAL-tree line number, but the bottom-up
    replacements just collapsed each copy's span (hi-lo+1 lines) to ONE call
    line, shrinking the buffer. ``first`` is first in EMIT order, NOT topmost in
    the file, so a copy may sit ABOVE this container; rebase the anchor by the net
    line-delta of every replacement whose span ends above it, or the def lands
    inside an earlier function's body (the same above/below partition
    inline_function uses so splice and deletions don't interfere)."""
    anchor = min(
        [container.lineno]
        + [d.lineno for d in getattr(container, "decorator_list", [])]
    )
    delta_above = sum(
        1 - (o.span_hi - o.span_lo + 1)
        for o in occs if o.span_hi < anchor
    )
    return anchor - 1 + delta_above


def _resolve_all(parsed: list, n_statements: int, sources: dict, trees: dict,
                 plan: RenamePlan) -> list | None:
    """Resolve every parsed occurrence into an :class:`_Occurrence`. Any unsafe /
    non-total-return one records its blocker (inside ``_resolve_total_return``)
    and aborts the whole plan — returns ``None``."""
    resolved: list[_Occurrence] = []
    for rel, line in parsed:  # type: ignore[misc]
        occ = _resolve_total_return(rel, line, n_statements, sources, trees, plan)
        if occ is None:
            return None
        resolved.append(occ)
    return resolved


def _choose_helper_name(resolved: list, trees: dict, rels: list,
                        plan: RenamePlan) -> str | None:
    """Human-readable name from the common tokens of the enclosing function names,
    falling back to the machine ``_shared_<n>`` scheme when none is clean/free.
    Records a blocker and returns ``None`` if no free name exists."""
    fn_names = [occ.fn.name for occ in resolved]
    helper_name = (_descriptive_helper_name(fn_names, trees, set(rels))
                   or _free_helper_name(trees, set(rels)))
    if helper_name is None:
        plan.blockers.append("could not find a free `_shared_<n>` helper name")
    return helper_name


def _emit_all_files(resolved: list, sources: dict, trees: dict,
                    first: _Occurrence, helper_name: str, helper_block: str,
                    call_line: str, plan: RenamePlan
                    ) -> tuple[dict, dict] | None:
    """Group occurrences by file and rewrite each (deterministic ``sorted`` order),
    accumulating ``(new_contents, edits_by_file)``. Returns ``None`` (after
    recording a blocker) if any emitted module would not parse."""
    first_dotted = _module_dotted(first.rel)
    by_file: dict[str, list[_Occurrence]] = {}
    for occ in resolved:
        by_file.setdefault(occ.rel, []).append(occ)

    new_contents: dict[str, str] = {}
    edits: dict[str, int] = {}
    for rel in sorted(by_file):
        occs = sorted(by_file[rel], key=lambda o: o.span_lo)
        new_source, emit_blocker = _emit_file(
            rel, occs, sources, trees, first, first_dotted,
            helper_name, helper_block, call_line)
        if new_source is None:
            plan.blockers.append(emit_blocker)
            return None
        new_contents[rel] = new_source
        edits[rel] = len(occs) + (1 if rel != first.rel else 0)
    return new_contents, edits


def _prepare(root: Path, block, plan: RenamePlan) -> dict | None:
    """Run the whole admissibility prelude — validate the block, parse occurrence
    locations, read & parse modules, resolve every occurrence, gate the shared
    signature, and pick a helper name. Each step records its own blocker; the
    first failure returns ``None``. On success returns a context dict with the
    ``sources``/``trees``, ``resolved`` occurrences, the common ``live_in``/
    ``live_out`` signature, the ``first`` occurrence, and the ``helper_name``."""
    validated = _validate_block(block, plan)
    if validated is None:
        return None
    occurrences, n_statements = validated

    parsed = [_parse_occurrence(o) for o in occurrences]
    if any(p is None for p in parsed):
        plan.blockers.append("malformed occurrence location(s)")
        return None

    rels = sorted({rel for rel, _ in parsed})  # type: ignore[misc]
    read = _read_modules(root, rels, plan)
    if read is None:
        return None
    sources, trees = read

    resolved = _resolve_all(parsed, n_statements, sources, trees, plan)
    if resolved is None:
        return None

    sig0 = _signature_gate(resolved, plan)
    if sig0 is None:
        return None

    helper_name = _choose_helper_name(resolved, trees, rels, plan)
    if helper_name is None:
        return None

    return {
        "sources": sources, "trees": trees, "resolved": resolved,
        "live_in": sig0[0], "live_out": sig0[1],
        "first": resolved[0], "helper_name": helper_name,
    }


def plan_dedup_total_return(project_root: str | Path, block) -> RenamePlan:
    """Plan lifting a TOTAL-RETURN exact-duplicate block into one shared helper.

    ``block`` is an exact-duplicate :class:`~app.engine.dedup.DuplicateBlock`
    (``occurrences`` are ``"module:lineno"`` of each copy's first statement) — the
    same input :func:`~app.execution.dedup_extract.plan_dedup_extract` consumes.
    This planner accepts ONLY the subset dedup_extract blocks for a non-tail
    return yet is provably safe: a block whose every exit path returns
    (:func:`_always_returns`). The whole block lifts verbatim into a returning
    helper and each copy becomes ``return _shared_n(<live_in>)``.

    Returns a :class:`RenamePlan` ready for ``apply_rename`` (suite-verified,
    auto-rollback). On any unsafe / ambiguous case the plan carries a blocker and
    empty ``new_contents`` — correctness and safety over coverage.
    """
    plan = RenamePlan(old=getattr(block, "fingerprint", "dedup"), new="_shared")

    ctx = _prepare(Path(project_root), block, plan)
    if ctx is None:
        return plan
    sources, trees, resolved = ctx["sources"], ctx["trees"], ctx["resolved"]
    live_in, live_out = ctx["live_in"], ctx["live_out"]
    first, helper_name = ctx["first"], ctx["helper_name"]

    helper_block = _build_helper_block(first, helper_name, live_in)
    # The block's own returns are inside the helper — return its result.
    call_line = f"return {helper_name}({', '.join(live_in)})\n"

    emitted = _emit_all_files(resolved, sources, trees, first, helper_name,
                              helper_block, call_line, plan)
    if emitted is None:
        return plan
    new_contents, edits = emitted

    stamp_multi_module_plan(plan, helper_name, first.rel, sources,
                            new_contents, edits)
    if not live_in and not live_out:
        plan.warnings.append(
            "the helper takes no parameters and returns nothing directly "
            "(it returns via the block's own returns) — confirm it's self-contained")
    return plan
