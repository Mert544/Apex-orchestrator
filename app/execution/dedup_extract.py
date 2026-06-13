"""Dedup-Extract — turn the duplication DETECTOR into an ACTION.

The duplication detector (:mod:`app.engine.dedup`) reports that an identical run
of statements appears in several places. This module is the hand that fixes it:
it lifts that duplicated run into ONE module-level helper and rewrites every copy
into a call to it — so the next bug-fix lands in a single place instead of being
silently forgotten in the other copies.

Given a :class:`~app.engine.dedup.DuplicateBlock` (whose ``occurrences`` are
``"module:lineno"`` locations of the first statement of each copy), Apex:
  - re-locates the contiguous statement run at each occurrence (reusing
    extract_method's statement-selection so it snaps to statement boundaries);
  - computes the data flow (live_in → parameters, live_out → return values) at
    EACH occurrence and requires the SIGNATURE to be identical everywhere — a
    clean shared helper has one interface, so structurally-divergent copies are
    a blocker, never a guess;
  - builds one ``def _shared_<n>(live_in...): <block> [return live_out]`` in the
    module of the first occurrence and replaces each copy with the call
    ``live_out = _shared_n(live_in)`` (a bare call when there's no live-out),
    adding ``from <first_module> import _shared_n`` to any OTHER module.

Conservative by design — a ``yield`` / ``await`` / nested-def / escaping
``break`` in the block blocks the whole plan. One control-flow shape IS lifted:
a block whose tail (and only) statement is ``return <value>`` becomes a
*returning* helper (``def _shared_n(...): <block ending in return>``) and each
copy becomes ``return _shared_n(...)`` — turning the common "the range contains
a return" blocker into a clean action. An EARLY (non-tail) return still blocks.
Apply is suite-verified with automatic rollback via the shared
:class:`RenamePlan` / ``apply_rename`` model, so even a data-flow corner case
can never ship a broken extraction. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _top_level_bindings
from app.execution.extract_method import (
    _NESTED_SCOPE_NODES,
    _blocking_reason,
    _data_flow,
    _enclosing_function,
    _has_unenclosed_jump,
    _reindent,
    _selected_statements,
)
from app.execution.unused_imports import strip_unused_imports

__all__ = ["plan_dedup_extract"]


def _module_dotted(rel: str) -> str:
    """Dotted import path of a ``foo/bar.py`` relative module ("foo.bar")."""
    return rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", ".")


def _parse_occurrence(occ: str) -> tuple[str, int] | None:
    """Split a ``"module:lineno"`` occurrence into ``(rel, lineno)``."""
    sep = occ.rfind(":")
    if sep <= 0:
        return None
    rel = occ[:sep]
    try:
        return rel, int(occ[sep + 1:])
    except ValueError:
        return None


def _locate_run(fn, start_line: int, n_statements: int):
    """The contiguous run of ``n_statements`` body statements of ``fn`` beginning
    at ``start_line``, or ``None`` when no such clean run exists (snaps to
    statement boundaries, reusing extract_method's selection)."""
    starters = [s for s in fn.body if s.lineno == start_line]
    if len(starters) != 1:
        return None
    first = starters[0]
    idx = fn.body.index(first)
    run = fn.body[idx:idx + n_statements]
    if len(run) != n_statements:
        return None
    end_line = max(getattr(s, "end_lineno", s.lineno) for s in run)
    # Round-trip through the shared selector so the span really is a contiguous,
    # complete-statement slice of the body (no surprises from overlapping lines).
    selected = _selected_statements(fn, start_line, end_line)
    if selected != run:
        return None
    return run


def _is_tail_return(run: list) -> bool:
    """The run ends in ``return <value>`` and that is its ONLY return — the safe
    shape to lift into a *returning* helper (the call site becomes
    ``return _shared_n(...)``)."""
    if not run or not isinstance(run[-1], ast.Return) or run[-1].value is None:
        return False
    returns = [n for s in run for n in ast.walk(s) if isinstance(n, ast.Return)]
    return len(returns) == 1 and returns[0] is run[-1]


def _block_reason(run: list) -> tuple[str | None, bool]:
    """``(reason, is_tail_return)``. A plain block defers to extract_method's
    ``_blocking_reason`` (a ``return`` anywhere blocks). A TAIL-return block is
    allowed — it becomes a returning helper — yet is still blocked for
    yield/await/global/nonlocal, a nested def/lambda, an EARLY (non-tail)
    ``return``, or an unenclosed ``break``/``continue``."""
    if not _is_tail_return(run):
        return _blocking_reason(run), False
    tail = run[-1]
    for stmt in run:
        for n in ast.walk(stmt):
            if isinstance(n, _NESTED_SCOPE_NODES):
                return ("the range defines a nested function/lambda — its scope "
                        "can't be analyzed; extract it separately first", False)
            if isinstance(n, (ast.Yield, ast.YieldFrom, ast.Await,
                              ast.Global, ast.Nonlocal)):
                return (f"the range contains `{type(n).__name__.lower()}` — moving "
                        "it into a helper would change control flow", False)
            if isinstance(n, ast.Return) and n is not tail:
                return ("the range has an early `return` before its tail — it "
                        "can't be one returning helper", False)
    if any(_has_unenclosed_jump(stmt) for stmt in run):
        return ("the range contains a `break`/`continue` whose loop is outside "
                "the selection — it can't be lifted out", False)
    return None, True


class _Occurrence:
    """One resolved copy of the duplicated block, with everything the plan needs."""

    __slots__ = ("rel", "source", "lines", "fn", "container", "stmts",
                 "live_in", "live_out", "span_lo", "span_hi", "tail_return")

    def __init__(self, rel, source, lines, fn, container, stmts,
                 live_in, live_out, span_lo, span_hi, tail_return):
        self.rel = rel
        self.source = source
        self.lines = lines
        self.fn = fn
        self.container = container
        self.stmts = stmts
        self.live_in = live_in
        self.live_out = live_out
        self.span_lo = span_lo
        self.span_hi = span_hi
        self.tail_return = tail_return


def _resolve_occurrence(root: Path, rel: str, start_line: int,
                        n_statements: int, sources: dict, trees: dict,
                        plan: RenamePlan) -> _Occurrence | None:
    """Resolve one ``module:lineno`` occurrence into an :class:`_Occurrence`,
    recording a blocker and returning ``None`` on any unsafe / ambiguous case."""
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

    reason, tail_return = _block_reason(run)
    if reason:
        plan.blockers.append(f"{rel}:{start_line}: {reason}")
        return None

    before = fn.body[:fn.body.index(run[0])]
    after = fn.body[fn.body.index(run[-1]) + 1:]
    live_in, live_out = _data_flow(fn, before, run, after)
    if tail_return:
        # The block unconditionally returns, so any fn-body statement after it is
        # unreachable — nothing flows out. The helper returns the value directly.
        live_out = []

    span_lo = run[0].lineno
    span_hi = max(getattr(s, "end_lineno", s.lineno) for s in run)
    return _Occurrence(rel, source, source.splitlines(keepends=True), fn,
                       container, run, live_in, live_out, span_lo, span_hi,
                       tail_return)


def _free_helper_name(trees: dict, rels: set[str]) -> str | None:
    """The first ``_shared_<n>`` name free at module level in every involved
    module (so the def and its imports never collide), or ``None`` if exhausted."""
    bound: set[str] = set()
    for rel in rels:
        bound |= _top_level_bindings(trees[rel])
    for n in range(1, 1000):
        name = f"_shared_{n}"
        if name not in bound:
            return name
    return None


def plan_dedup_extract(project_root: str | Path, block) -> RenamePlan:
    """Plan the extraction of a :class:`DuplicateBlock` into one shared helper.

    Returns a :class:`RenamePlan` ready for ``apply_rename`` (suite-verified,
    auto-rollback). On any unsafe / ambiguous case the plan carries a blocker and
    empty ``new_contents`` — correctness and safety over coverage.
    """
    plan = RenamePlan(old=getattr(block, "fingerprint", "dedup"),
                      new="_shared")
    root = Path(project_root)

    occurrences = list(getattr(block, "occurrences", []) or [])
    n_statements = int(getattr(block, "lines", 0) or 0)
    if len(occurrences) < 2:
        plan.blockers.append("a shared helper needs at least two occurrences")
        return plan
    if n_statements < 1:
        plan.blockers.append("block has no statements to extract")
        return plan

    parsed = [_parse_occurrence(o) for o in occurrences]
    if any(p is None for p in parsed):
        plan.blockers.append("malformed occurrence location(s)")
        return plan

    # Read & parse every involved module once (deterministic order).
    sources: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    rels = sorted({rel for rel, _ in parsed})  # type: ignore[misc]
    for rel in rels:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            plan.blockers.append(f"cannot read {rel}")
            return plan
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError as e:
            plan.blockers.append(f"{rel} doesn't parse: {e}")
            return plan
        sources[rel] = text

    # Resolve each occurrence; any unsafe one blocks the whole plan.
    resolved: list[_Occurrence] = []
    for rel, line in parsed:  # type: ignore[misc]
        occ = _resolve_occurrence(root, rel, line, n_statements, sources,
                                  trees, plan)
        if occ is None:
            return plan
        resolved.append(occ)

    # The shared helper has ONE interface: require an identical live-in/live-out
    # signature across all copies, else they aren't a clean shared helper.
    sig0 = (resolved[0].live_in, resolved[0].live_out)
    for occ in resolved[1:]:
        if (occ.live_in, occ.live_out) != sig0:
            plan.blockers.append(
                "occurrences have different data-flow signatures "
                f"(params/returns differ: {sig0} vs "
                f"{(occ.live_in, occ.live_out)}) — not a clean shared helper")
            return plan
    live_in, live_out = sig0

    first = resolved[0]
    tail_return = first.tail_return
    if any(occ.tail_return != tail_return for occ in resolved[1:]):
        plan.blockers.append("occurrences disagree on tail-return shape — "
                             "not a clean shared helper")
        return plan
    first_dotted = _module_dotted(first.rel)
    helper_name = _free_helper_name(trees, set(rels))
    if helper_name is None:
        plan.blockers.append("could not find a free `_shared_<n>` helper name")
        return plan

    # ── Build the helper from the FIRST occurrence's real source text. ──
    range_lines = first.lines[first.span_lo - 1:first.span_hi]
    base_indent = len(range_lines[0]) - len(range_lines[0].lstrip())
    body_lines = _reindent(range_lines, base_indent)
    if live_out:
        body_lines.append("    return " + ", ".join(live_out))
    helper_src = [f"def {helper_name}({', '.join(live_in)}):"] + body_lines
    helper_block = "\n".join(helper_src) + "\n\n\n"

    call_expr = f"{helper_name}({', '.join(live_in)})"

    def _call_line(indent: str) -> str:
        if tail_return:
            # The block's own `return <expr>` is inside the helper — return its result.
            return f"{indent}return {call_expr}\n"
        if live_out:
            return f"{indent}{', '.join(live_out)} = {call_expr}\n"
        return f"{indent}{call_expr}\n"

    # ── Group occurrences by file; apply bottom-up within each file. ──
    by_file: dict[str, list[_Occurrence]] = {}
    for occ in resolved:
        by_file.setdefault(occ.rel, []).append(occ)

    new_contents: dict[str, str] = {}
    edits: dict[str, int] = {}
    for rel in sorted(by_file):
        occs = sorted(by_file[rel], key=lambda o: o.span_lo)
        lines = list(sources[rel].splitlines(keepends=True))

        # Replace each copy with a call, bottom-up so earlier spans stay valid.
        for occ in sorted(occs, key=lambda o: o.span_lo, reverse=True):
            indent = " " * (len(occ.lines[occ.span_lo - 1])
                            - len(occ.lines[occ.span_lo - 1].lstrip()))
            lines[occ.span_lo - 1:occ.span_hi] = [_call_line(indent)]

        if rel == first.rel:
            # Insert the helper above the first occurrence's container.
            container = first.container
            insert_at = min(
                [container.lineno]
                + [d.lineno for d in getattr(container, "decorator_list", [])]
            ) - 1
            lines[insert_at:insert_at] = [helper_block]
        else:
            # Another module: import the helper at the top (after __future__).
            import_line = f"from {first_dotted} import {helper_name}\n"
            lines.insert(_import_insert_index(trees[rel]), import_line)

        new_source = "".join(lines)
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            plan.blockers.append(
                f"{rel}: extraction would not parse ({e})")
            return plan

        # Gate-clean: lifting the block out can strand the imports it used,
        # leaving the emitted module with `F401 imported but unused`. Reuse the
        # unused-import detector on the NEW source and drop exactly those dead
        # top-level imports (`from __future__` / star-affected names are never
        # touched, and the result is re-parse-checked inside the helper). Same
        # extraction, same occurrences replaced — only now-dead imports go.
        cleaned = strip_unused_imports(new_source)
        if cleaned is not None:
            new_source = cleaned

        new_contents[rel] = new_source
        edits[rel] = len(occs) + (1 if rel != first.rel else 0)

    plan.new = helper_name
    plan.defined_in = first.rel
    plan.originals = {rel: sources[rel] for rel in new_contents}
    plan.new_contents = new_contents
    plan.edits_by_file = edits
    if not live_in and not live_out:
        plan.warnings.append(
            "the helper takes no parameters and returns nothing — confirm the "
            "block is self-contained")
    return plan


def _import_insert_index(tree: ast.Module) -> int:
    """Line index (0-based) to insert an import: after a leading module docstring
    and any ``from __future__`` imports, before other code."""
    insert_line = 1
    body = tree.body
    i = 0
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(getattr(body[0], "value", None), ast.Constant)
            and isinstance(body[0].value.value, str)):
        insert_line = (body[0].end_lineno or body[0].lineno) + 1
        i = 1
    while i < len(body) and isinstance(body[i], ast.ImportFrom) \
            and body[i].module == "__future__":
        insert_line = (body[i].end_lineno or body[i].lineno) + 1
        i += 1
    return max(0, insert_line - 1)
