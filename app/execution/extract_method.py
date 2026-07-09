"""Extract Method — turn a run of statements into a named helper.

The engine's roadmap keeps surfacing *"extract a shared helper"* for long
functions (``facet_evidence._long_functions``); this is the hand that performs
it.  Given a line range inside one function, Apex computes the data flow —
which names flow IN (become parameters) and which flow OUT (become return
values) — builds a module-level helper, and replaces the range with a call to
it.

Conservative by design — any ambiguity is a **blocker**, never a guess:
  - the range must be a contiguous run of complete statements in one function;
  - the function must be closure-free (top-level, or a method of a top-level
    class) — a nested function's free variables can't be parameterized safely;
  - ``return`` / ``yield`` / ``await`` / ``global`` / ``nonlocal`` in the range
    block (moving them out would change the function's control flow);
  - a nested ``def`` / ``lambda`` in the range blocks (its scope can't be
    analyzed by this pass);
  - the helper name must be free at module level;
  - a caller-supplied :func:`seam_fingerprint` that no longer matches the
    statements actually sitting at the requested lines blocks — the file
    drifted since the seam was chosen, so ``plan_extract`` refuses rather than
    silently splicing whatever now occupies that line range (see
    ``plan_extract``'s ``expected_fingerprint`` parameter).

Apply is suite-verified with automatic rollback — exactly like every Apex
change, so even a data-flow corner case can never ship a broken extraction.
Deterministic, stdlib-only; reuses :class:`RenamePlan` / ``apply_rename``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _top_level_bindings

__all__ = ["plan_extract", "suggest_extractions", "seam_fingerprint"]

# Statements whose presence in the range would change control-flow semantics if
# relocated into a helper (or that this pass deliberately doesn't analyze).
_CONTROL_NODES = (ast.Return, ast.Yield, ast.YieldFrom, ast.Await,
                  ast.Global, ast.Nonlocal)
_NESTED_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMP_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _enclosing_function(tree: ast.Module, start: int, end: int):
    """The (function, top_level_container) whose body holds the range, or
    (None, None). ``container`` is the module-level statement to insert the
    helper before (the function itself, or the class for a method)."""
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = _function_covering(top, start, end)
            if fn is top:
                return top, top
        elif isinstance(top, ast.ClassDef):
            for item in top.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = _function_covering(item, start, end)
                    if fn is item:
                        return item, top
    return None, None


def _function_covering(fn, start: int, end: int):
    """``fn`` if [start,end] lies within its body, else None (only this exact
    function — a range inside a NESTED def returns None, so it blocks)."""
    body = fn.body
    if not body:
        return None
    lo = body[0].lineno
    hi = max(getattr(s, "end_lineno", s.lineno) for s in body)
    return fn if lo <= start and end <= hi else None


def _selected_statements(fn, start: int, end: int) -> list:
    """The contiguous run of top-level body statements fully inside [start,end]."""
    chosen = [s for s in fn.body
              if start <= s.lineno and getattr(s, "end_lineno", s.lineno) <= end]
    if not chosen:
        return []
    # Must be a contiguous slice of the body (no gaps that skip a statement).
    first_idx = fn.body.index(chosen[0])
    last_idx = fn.body.index(chosen[-1])
    if fn.body[first_idx:last_idx + 1] != chosen:
        return []
    return chosen


def _loads(nodes: list) -> set[str]:
    """Every name read (Load context) anywhere in ``nodes``."""
    out: set[str] = set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                out.add(n.id)
    return out


def _comp_targets(nodes: list) -> set[str]:
    """Comprehension iteration variables — scoped to the comprehension in Py3,
    so they are NOT function locals and must not be treated as defined names."""
    out: set[str] = set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, _COMP_NODES):
                for gen in n.generators:
                    for t in ast.walk(gen.target):
                        if isinstance(t, ast.Name):
                            out.add(t.id)
    return out


def _stores(nodes: list) -> set[str]:
    """Names assigned (Store context) in ``nodes`` — function locals defined
    here. Comprehension targets are excluded (they don't leak)."""
    comp = _comp_targets(nodes)
    out: set[str] = set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                out.add(n.id)
    return out - comp


def _target_names(target) -> set[str]:
    """Names bound by one assignment target — a bare ``Name`` or a
    ``Tuple``/``List``/``Starred`` unpacking of them."""
    return {n.id for n in ast.walk(target)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}


def _definitely_assigned(stmts: list) -> set[str]:
    """Names bound on EVERY path that runs ``stmts`` to normal completion — the
    targets of the range's TOP-LEVEL ``=`` / annotated-``=``-with-value / ``+=`` /
    ``with ... as`` statements.

    A name bound only inside a NESTED block (an ``if``/``for``/``while``/``try``/
    ``with`` body — e.g. ``if bad: msg = ...; raise``) is NOT definitely assigned
    at the range's normal exit, so it must never become a helper RETURN value:
    ``return <maybe-unbound>`` raises ``UnboundLocalError`` on the path that
    skipped the block. This is the real defect it guards — extracting
    ``packaging.licenses.canonicalize_license_expression`` returned ``message``,
    which is set only inside an ``if ...: raise``. Extract-method already blocks
    ranges containing ``return``/``yield`` (see ``_CONTROL_NODES``); a nested
    ``raise`` only ever EXITS, so a top-level statement still binds definitely on
    the normal path."""
    out: set[str] = set()
    for s in stmts:
        if isinstance(s, ast.Assign):
            for t in s.targets:
                out |= _target_names(t)
        elif isinstance(s, ast.AnnAssign) and s.value is not None:
            out |= _target_names(s.target)
        elif isinstance(s, ast.AugAssign):
            out |= _target_names(s.target)
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for item in s.items:
                if item.optional_vars is not None:
                    out |= _target_names(item.optional_vars)
    return out


def _augmented_targets(nodes: list) -> set[str]:
    """AugAssign targets (``x += 1``) — both a read of the prior value and a
    store, so they belong to live-in when the name pre-exists."""
    out: set[str] = set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                out.add(n.target.id)
    return out


def _function_param_names(fn) -> set[str]:
    a = fn.args
    names: set[str] = set()
    for grp in (a.posonlyargs, a.args, a.kwonlyargs):
        names.update(p.arg for p in grp)
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)


def _has_unenclosed_jump(node: ast.AST, in_loop: bool = False) -> bool:
    """True if ``node`` holds a ``break``/``continue`` that is NOT inside a loop
    within this subtree — such a jump would escape the extracted code. A jump
    whose own loop is also selected stays valid, so it doesn't block."""
    if isinstance(node, (ast.Break, ast.Continue)):
        return not in_loop
    if isinstance(node, _NESTED_SCOPE_NODES):
        return False  # a nested scope's jumps belong to its own loops
    child_in_loop = in_loop or isinstance(node, _LOOP_NODES)
    for child in ast.iter_child_nodes(node):
        # A loop's `orelse` runs outside the loop body, but break/continue there
        # would themselves be syntax errors, so the simple flag suffices.
        if _has_unenclosed_jump(child, child_in_loop):
            return True
    return False


def _blocking_reason(stmts: list) -> str | None:
    """The reason this range can't be relocated into a helper, or None when it
    is safe. Single source of truth for both the planner and the suggester."""
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, _NESTED_SCOPE_NODES):
                return ("the range defines a nested function/lambda — its scope "
                        "can't be analyzed; extract it separately first")
            if isinstance(n, _CONTROL_NODES):
                kind = type(n).__name__.lower()
                return (f"the range contains `{kind}` — moving it into a helper "
                        "would change the function's control flow")
    for stmt in stmts:
        if _has_unenclosed_jump(stmt):
            return ("the range contains a `break`/`continue` whose loop is outside "
                    "the selection — it can't be lifted out")
    return None


def _has_blocking_control(stmts: list, plan: RenamePlan) -> bool:
    """Record a blocker for any relocate-unsafe node in the range."""
    reason = _blocking_reason(stmts)
    if reason:
        plan.blockers.append(reason)
        return True
    return False


def _data_flow(fn, before: list, stmts: list, after: list) -> tuple[list[str], list[str]]:
    """The (live_in, live_out) of extracting ``stmts`` from ``fn``: names read
    from the surrounding scope become parameters, names defined here and read
    afterward become return values. Single source of truth for the planner and
    the suggester.

    ``live_out`` here is the RAW defined∩read-after set. Callers that would emit a
    ``return`` for these names must ALSO reject the range when
    :func:`_unsafe_conditional_outputs` is non-empty — a name defined only
    conditionally cannot be soundly returned (see that guard)."""
    params_and_prior = _function_param_names(fn) | _stores(before)
    reads = _loads(stmts) | _augmented_targets(stmts)
    live_in = sorted(n for n in reads if n in params_and_prior)

    defined = _stores(stmts) | _augmented_targets(stmts)
    reads_after = _loads(after)
    live_out = sorted(n for n in defined if n in reads_after)
    return live_in, live_out


def _conditional_output_split(fn, before: list, stmts: list,
                              after: list) -> tuple[list[str], list[str]]:
    """Split the range's read-after outputs that are NOT definitely assigned into
    ``(extra_in, unsafe)``.

    A name (re)assigned only CONDITIONALLY in the range (inside an ``if``/``for``/
    ``try``/… body, so not bound on every path to the range's normal exit) but
    read AFTER the range must be RETURNED (else the reassignment is lost) AND be
    bound on entry (else the ``return`` is maybe-unbound → ``UnboundLocalError``).

    * ``extra_in`` — names that PRE-EXIST the range (a parameter or a local set
      before it). These are threaded through as extra helper parameters (passed IN
      and returned), which is sound: bound on entry, updated conditionally,
      returned. A finder loop over a ``found`` pre-set to ``None`` is fine.
    * ``unsafe`` — names that do NOT pre-exist: a brand-new binding made only
      inside a branch (e.g. ``packaging.licenses`` set ``message`` only inside an
      ``if ...: raise``). These cannot be made bound, so the caller REFUSES the
      extraction rather than land an ``UnboundLocalError`` a partial suite may not
      catch (the real fake-green defect this guards)."""
    params_and_prior = _function_param_names(fn) | _stores(before)
    definite = _definitely_assigned(stmts)
    defined = _stores(stmts) | _augmented_targets(stmts)
    reads_after = _loads(after)
    conditional = [n for n in defined if n in reads_after and n not in definite]
    extra_in = sorted(n for n in conditional if n in params_and_prior)
    unsafe = sorted(n for n in conditional if n not in params_and_prior)
    return extra_in, unsafe


def _names_with_ctx(nodes: list, ctx_type: type) -> set[str]:
    """Names in ``nodes`` whose context is ``ctx_type`` (Load → reads, Store →
    assignments) — the per-statement form of :func:`_loads` / raw stores."""
    return {n.id for n in nodes
            if isinstance(n, ast.Name) and isinstance(n.ctx, ctx_type)}


def _augassign_targets(nodes: list) -> set[str]:
    """AugAssign name targets (``x += 1``) found in ``nodes``."""
    return {n.target.id for n in nodes
            if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)}


def _comprehension_targets(nodes: list) -> set[str]:
    """Comprehension iteration variables among ``nodes`` — scoped to their comp,
    so they're not function locals (the per-statement form of comp-target walk)."""
    out: set[str] = set()
    for n in nodes:
        if isinstance(n, _COMP_NODES):
            for gen in n.generators:
                for t in ast.walk(gen.target):
                    if isinstance(t, ast.Name):
                        out.add(t.id)
    return out


def _statement_blocks(stmt, nodes: list) -> bool:
    """True if ``stmt`` is relocate-unsafe: a nested scope / control node in its
    subtree, or a ``break``/``continue`` whose loop lies outside it."""
    if any(isinstance(n, (*_NESTED_SCOPE_NODES, *_CONTROL_NODES)) for n in nodes):
        return True
    return _has_unenclosed_jump(stmt)


class _StmtFacts:
    """The data-flow primitives of a *single* statement, walked exactly once.

    ``suggest_extractions`` enumerates O(n²) overlapping windows of a function
    body, and every window's :func:`_blocking_reason` / :func:`_data_flow` re-walks
    the same statements again and again. These per-statement sets let the scan
    union precomputed facts instead — the byte-identical decomposition of the
    list-level helpers above:

    * ``_loads(window)``            == union of every ``loads`` in the window
    * ``_augmented_targets(window)``== union of every ``aug`` in the window
    * ``_stores(window)``           == ``union(raw_stores) - union(comp)`` over it
      (the comp subtraction is done on the *whole* window, matching ``_stores``
      which subtracts ``_comp_targets(nodes)`` from the union — a name that is a
      store in one statement and a comp-target in another stays excluded)
    * ``_blocking_reason(window) is not None`` == any statement's ``blocks`` flag
      (the list-level reason walks each statement independently, so a window is
      unsafe iff at least one of its statements is — the suggester only needs the
      boolean, never the specific message string)
    """

    __slots__ = ("loads", "aug", "raw_stores", "comp", "blocks", "definite")

    def __init__(self, stmt) -> None:
        # Walk the statement exactly once, then classify the flat node list with
        # pure helpers — same sets, same single traversal as the inlined loop.
        nodes = list(ast.walk(stmt))
        self.loads = _names_with_ctx(nodes, ast.Load)
        self.raw_stores = _names_with_ctx(nodes, ast.Store)
        self.aug = _augassign_targets(nodes)
        self.comp = _comprehension_targets(nodes)
        self.blocks = _statement_blocks(stmt, nodes)
        # Names this ONE statement binds DEFINITELY (top-level =/+=/with-as), so a
        # window can tell a sound return value from a maybe-unbound one — the
        # suggester mirror of ``_definitely_assigned`` (which the planner uses).
        self.definite = _definitely_assigned([stmt])


def _reindent(src_lines: list[str], base_indent: int) -> list[str]:
    """Dedent the range by its own indent, re-indent to 4 spaces under `def`."""
    out: list[str] = []
    for line in src_lines:
        stripped = line.rstrip("\n")
        if not stripped.strip():
            out.append("")  # blank line stays blank
            continue
        body = stripped[base_indent:] if stripped[:base_indent].isspace() or not stripped[:base_indent] else stripped.lstrip()
        out.append("    " + body)
    return out


def _read_and_parse(path: Path, file_rel: str, helper_name: str,
                    start_line: int, end_line: int):
    """Read ``path`` and validate the request, returning ``(source, tree, None)``
    on success or ``(None, None, blocker)`` for the first failing precondition —
    the byte-identical prelude of :func:`plan_extract`'s guard chain."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None, None, f"cannot read {file_rel}"
    if not helper_name.isidentifier():
        return None, None, f"`{helper_name}` is not a valid function name"
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError) as e:
        return None, None, f"{file_rel} doesn't parse: {e}"
    if start_line > end_line:
        return None, None, "start line must be <= end line"
    if helper_name in _top_level_bindings(tree):
        return None, None, (
            f"`{helper_name}` is already defined at module level — pick another name")
    return source, tree, None


def _locate_statements(tree: ast.Module, start_line: int, end_line: int):
    """Resolve the range to its enclosing function and contiguous statement run,
    returning ``(fn, container, stmts, None)`` or ``(None, None, None, blocker)``."""
    fn, container = _enclosing_function(tree, start_line, end_line)
    if fn is None:
        return None, None, None, (
            f"lines {start_line}-{end_line} aren't inside one top-level "
            "function/method body (nested-function ranges aren't supported)")
    stmts = _selected_statements(fn, start_line, end_line)
    if not stmts:
        return None, None, None, (
            "the range must cover a contiguous run of complete statements "
            "in the function body (it snaps to statement boundaries)")
    return fn, container, stmts, None


def _stmt_run_fingerprint(stmts: list) -> str:
    """A normalized, position-free structural fingerprint of a statement run:
    each statement's ``ast.dump()`` (which omits ``lineno``/``col_offset``, so
    a pure line-shift never changes it) joined by a separator that cannot
    appear inside one. Mirrors :func:`app.execution._dedup_helpers.
    _identity_blocker`'s identity check — that rail compares several
    occurrences resolved in the SAME call; this compares ONE run across TIME
    (a plan-time snapshot vs. whatever ``plan_extract`` locates at apply
    time)."""
    return "\x1e".join(ast.dump(s) for s in stmts)


def seam_fingerprint(tree: ast.Module, start_line: int, end_line: int) -> str | None:
    """The structural fingerprint :func:`plan_extract` would compute for the
    statement run at ``(start_line, end_line)`` in ``tree`` right now, or
    ``None`` when the range doesn't resolve to one (nothing to fingerprint —
    the caller has nothing sound to compare against either).

    A caller that captures a seam's line numbers well before the actual apply
    — e.g. the objective compiler's ``Move.build_plan`` closures, built from a
    scan against the tree at the TOP of a pass but only invoked once earlier
    moves in the SAME pass have already run and possibly edited the file —
    calls this once at scan time and hands the result to :func:`plan_extract`
    as ``expected_fingerprint``: an apply-time re-verification that the
    statements now at those lines are still the ones the plan was built
    against, not whatever the file drifted to in between."""
    _fn, _container, stmts, blocker = _locate_statements(tree, start_line, end_line)
    if blocker is not None:
        return None
    return _stmt_run_fingerprint(stmts)


def _build_helper_block(range_lines: list[str], base_indent: int,
                        helper_name: str, live_in: list[str],
                        live_out: list[str]) -> str:
    """The module-level helper ``def`` text (with trailing blank lines) for the
    reindented range and its data-flow interface."""
    body_lines = _reindent(range_lines, base_indent)
    if live_out:
        body_lines.append("    return " + ", ".join(live_out))
    helper_src = [f"def {helper_name}({', '.join(live_in)}):"] + body_lines
    return "\n".join(helper_src) + "\n\n\n"


def _build_call_line(call_indent: str, helper_name: str,
                     live_in: list[str], live_out: list[str]) -> str:
    """The replacement call line for the extracted range."""
    call_expr = f"{helper_name}({', '.join(live_in)})"
    if live_out:
        return f"{call_indent}{', '.join(live_out)} = {call_expr}\n"
    return f"{call_indent}{call_expr}\n"


def _assemble_source(lines: list[str], span_lo: int, span_hi: int,
                     call_line: str, helper_block: str, container) -> str:
    """Apply the two edits bottom-up: replace the range with the call, then
    insert the helper above the container (and its decorators)."""
    new_lines = list(lines)
    new_lines[span_lo - 1:span_hi] = [call_line]
    insert_at = min([container.lineno] +
                    [d.lineno for d in getattr(container, "decorator_list", [])]) - 1
    new_lines[insert_at:insert_at] = [helper_block]
    return "".join(new_lines)


def plan_extract(project_root: str | Path, file_rel: str,
                 start_line: int, end_line: int, helper_name: str,
                 expected_fingerprint: str | None = None) -> RenamePlan:
    """Build the single-file extract-method plan for ``file_rel``.

    ``expected_fingerprint`` (optional, default ``None`` ⇒ unchanged behaviour)
    is a :func:`seam_fingerprint` captured against an EARLIER read of the tree —
    typically at seam-suggestion time, before other moves in the same campaign
    pass had a chance to edit ``file_rel``. When supplied, the statements
    actually located at ``(start_line, end_line)`` right now are re-fingerprinted
    and compared: a mismatch means the file drifted since the seam was chosen,
    so the plan is REFUSED with a ``stale seam`` blocker instead of silently
    extracting whatever now occupies that line range — line numbers alone are
    not a safe anchor across time. Every caller that omits the argument (the
    ``apex extract`` CLI's human-typed line numbers, direct tests) is
    byte-identical to before this parameter existed."""
    plan = RenamePlan(old=f"{file_rel}:{start_line}-{end_line}", new=helper_name)
    path = Path(project_root) / file_rel

    source, tree, blocker = _read_and_parse(
        path, file_rel, helper_name, start_line, end_line)
    if blocker is not None:
        plan.blockers.append(blocker)
        return plan

    fn, container, stmts, blocker = _locate_statements(tree, start_line, end_line)
    if blocker is not None:
        plan.blockers.append(blocker)
        return plan
    if (expected_fingerprint is not None
            and _stmt_run_fingerprint(stmts) != expected_fingerprint):
        plan.blockers.append(
            f"stale seam: {file_rel}:{start_line}-{end_line} no longer holds "
            "the statements this plan was built against — the file changed "
            "since the seam was chosen; replan before applying")
        return plan
    if _has_blocking_control(stmts, plan):
        return plan

    before = fn.body[:fn.body.index(stmts[0])]
    after = fn.body[fn.body.index(stmts[-1]) + 1:]
    live_in, live_out = _data_flow(fn, before, stmts, after)
    extra_in, unsafe_out = _conditional_output_split(fn, before, stmts, after)
    if unsafe_out:
        # A name the range assigns only CONDITIONALLY (inside an if/for/try/…
        # body — e.g. `if bad: msg = ...; raise`) that does NOT pre-exist is read
        # after the range. The helper would have to `return` it though it may be
        # unbound at the exit, yielding an UnboundLocalError on the path that
        # skipped the block. Refuse rather than land a change that fake-greens
        # (the covering suite may not exercise that path — packaging.licenses).
        plan.blockers.append(
            f"the range assigns {', '.join(f'`{n}`' for n in unsafe_out)} only "
            "conditionally but it is used after the range — returning a "
            "maybe-unbound value would be unsound; not extracting")
        return plan
    # A pre-existing name reassigned only conditionally in the range must be
    # passed IN as well as returned, so it is bound on every path (finder loop).
    # Empty ``extra_in`` folds to a harmless no-op (``live_in`` unchanged).
    live_in = sorted(set(live_in) | set(extra_in))

    # Build the helper and the replacement call from the real source text.
    lines = source.splitlines(keepends=True)
    span_lo = stmts[0].lineno
    span_hi = max(getattr(s, "end_lineno", s.lineno) for s in stmts)
    range_lines = lines[span_lo - 1:span_hi]
    base_indent = len(range_lines[0]) - len(range_lines[0].lstrip())

    helper_block = _build_helper_block(
        range_lines, base_indent, helper_name, live_in, live_out)
    call_line = _build_call_line(" " * base_indent, helper_name, live_in, live_out)
    new_source = _assemble_source(
        lines, span_lo, span_hi, call_line, helper_block, container)

    # Sanity: the result must still parse (a malformed extraction is a blocker,
    # not a silent corrupt write).
    try:
        ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError) as e:
        plan.blockers.append(f"extraction would not parse ({e}) — range may "
                             "split a statement; adjust the line range")
        return plan

    plan.originals[file_rel] = source
    plan.new_contents[file_rel] = new_source
    plan.edits_by_file[file_rel] = 1
    if not live_in and not live_out:
        plan.warnings.append("the helper takes no parameters and returns "
                             "nothing — confirm the range is self-contained")
    return plan


# ── Suggestion: where in a long function is the cleanest seam to extract? ──
_SUGGEST_MIN_STMTS = 3       # a run shorter than this isn't worth a helper
_SUGGEST_MIN_LINES = 6       # ...nor one that saves fewer lines than this
_SUGGEST_MAX_LINES = 40      # ...nor one so big the helper is itself a long fn
_SUGGEST_MAX_RETURNS = 4     # a helper returning more than this is an ugly seam
_SUGGEST_MAX_PARAMS = 5      # ...and one this wide isn't a clean seam either
_SUGGEST_FN_FLOOR = 40       # only mine functions at least this many lines tall
_SUGGEST_MAX_BODY = 60       # bound the O(n²) scan on pathological bodies


def _iter_closure_free_functions(tree: ast.Module):
    """Top-level functions and methods of top-level classes (no closures), each
    with the module-level container the helper would sit before."""
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield top, top
        elif isinstance(top, ast.ClassDef):
            for item in top.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield item, top


def _is_minable_function(fn) -> bool:
    """True when ``fn`` is tall enough and has a body the O(n²) scan will mine."""
    span = (fn.end_lineno or fn.lineno) - fn.lineno + 1
    if span < _SUGGEST_FN_FLOOR:
        return False
    return _SUGGEST_MIN_STMTS <= len(fn.body) <= _SUGGEST_MAX_BODY


def _prefix_stores(facts: list) -> list[set[str]]:
    """``prefix_stores[i] == _stores(body[:i])`` — locals defined before stmt i."""
    out: list[set[str]] = [set()]
    raw_acc: set[str] = set()
    comp_acc: set[str] = set()
    for f in facts:
        raw_acc = raw_acc | f.raw_stores
        comp_acc = comp_acc | f.comp
        out.append(raw_acc - comp_acc)
    return out


def _suffix_loads(facts: list) -> list[set[str]]:
    """``suffix_loads[j] == _loads(body[j:])`` — names read at/after stmt j."""
    n = len(facts)
    out: list[set[str]] = [set()] * (n + 1)
    loads_acc: set[str] = set()
    for k in range(n - 1, -1, -1):
        loads_acc = loads_acc | facts[k].loads
        out[k] = loads_acc
    return out


def _scan_function(fn) -> dict | None:
    """The single best contiguous run to extract from ``fn``, or None — the seam
    with the highest score (most lines saved for the smallest interface)."""
    body = fn.body
    n = len(body)
    # Walk each statement once; the O(n²) window scan below reuses these
    # per-statement sets instead of re-walking overlapping ranges (the
    # documented byte-identical decomposition of the list-level helpers).
    facts = [_StmtFacts(s) for s in body]
    line_lo = [s.lineno for s in body]
    line_hi = [getattr(s, "end_lineno", s.lineno) for s in body]
    prefix_stores = _prefix_stores(facts)
    suffix_loads = _suffix_loads(facts)
    param_names = _function_param_names(fn)

    # Never let an extraction window START at (and so sweep away) a leading
    # docstring: a public function's docstring is public API, and relocating it
    # into a private helper drops ``fn.__doc__`` to None (the real regression seen
    # extracting ``toml.loads``). The docstring stays put; windows begin after it.
    first = 1 if (n and ast.get_docstring(fn) is not None) else 0

    best: tuple[int, dict] | None = None
    for i in range(first, n):
        params_and_prior = param_names | prefix_stores[i]
        windows = _windows_from(fn, i, facts, line_lo, line_hi,
                                params_and_prior, suffix_loads)
        best = _better(best, windows)
    return best[1] if best is not None else None


def _better(best: tuple[int, dict] | None, windows):
    """Fold ``(key, candidate)`` pairs into ``best``, keeping the highest key."""
    for key, cand in windows:
        if best is None or key > best[0]:
            best = (key, cand)
    return best


def _windows_from(fn, i: int, facts: list, line_lo: list, line_hi: list,
                  params_and_prior: set[str], suffix_loads: list):
    """Yield ``(tie_break_key, candidate)`` for every viable window ``[i, j)``.

    Grows the window statement by statement, accumulating its data-flow sets in
    O(1) per step rather than re-walking each window."""
    n = len(facts)
    start = line_lo[i]
    win_loads: set[str] = set()
    win_aug: set[str] = set()
    win_raw: set[str] = set()
    win_comp: set[str] = set()
    win_definite: set[str] = set()
    win_end = 0
    win_blocked = False
    for j in range(i + 1, n + 1):
        f = facts[j - 1]
        win_loads |= f.loads
        win_aug |= f.aug
        win_raw |= f.raw_stores
        win_comp |= f.comp
        win_definite |= f.definite
        if line_hi[j - 1] > win_end:
            win_end = line_hi[j - 1]
        if f.blocks:
            win_blocked = True
        cand = _window_candidate(fn, i, j, n, start, win_end, win_blocked,
                                 win_loads, win_aug, win_raw, win_comp,
                                 win_definite, params_and_prior, suffix_loads)
        if cand is not None:
            # Deterministic tie-break: higher score, then earlier/smaller span.
            key = (cand["_score"], -cand["start"], -(cand["end"] - cand["start"]))
            del cand["_score"]
            yield key, cand


def _window_shape_ok(i: int, j: int, n: int, lines_saved: int,
                     win_blocked: bool) -> bool:
    """The size/blocker gates a window must clear before its interface matters:
    long enough run, not the whole body, relocate-safe, right line span."""
    if j - i < _SUGGEST_MIN_STMTS:
        return False
    if j - i == n:
        return False  # extracting the WHOLE body is a rename, not a seam
    if win_blocked:
        return False
    return _SUGGEST_MIN_LINES <= lines_saved <= _SUGGEST_MAX_LINES


def _suggest_helper_name(fn_name: str) -> str:
    """A module-level helper name for a seam extracted from ``fn_name``.

    The helper is inserted at module level, but its replacement call sits in the
    original (possibly class-body) scope. A name that *begins* with ``_`` would
    be class-private name-mangled at that unqualified call site
    (``__deserialize_part`` → ``_ClassName__deserialize_part``) and resolve to a
    name that doesn't exist → ``NameError`` at runtime — and since mangling is
    name-resolution, not syntax, the plan still parses, so it slips past the
    plan-time parse guard and only fails when the suite runs.

    Stripping the LEADING underscores and using a distinctive ``extracted_``
    prefix keeps every real candidate (a private method like ``_deserialize``
    still gets a clean seam) while never colliding with a real public symbol:
    ``_deserialize`` → ``extracted_deserialize_part``, ``process`` →
    ``extracted_process_part``, ``__init__`` → ``extracted_init___part``
    (trailing underscores are kept — they don't mangle). An all-underscore name
    falls back to ``extracted_fn_part`` via the ``or "fn"`` guard. The result is
    always a valid identifier with no leading underscore; the apply-time
    ``isidentifier()`` and module-level collision guards stay the safety net for
    the rare residual clash."""
    stem = fn_name.lstrip("_") or "fn"
    return f"extracted_{stem}_part"


def _window_candidate(fn, i: int, j: int, n: int, start: int, win_end: int,
                      win_blocked: bool, win_loads: set[str], win_aug: set[str],
                      win_raw: set[str], win_comp: set[str],
                      win_definite: set[str],
                      params_and_prior: set[str], suffix_loads: list) -> dict | None:
    """The candidate dict for window ``[i, j)`` (with a private ``_score``), or
    None when the window fails a seam-quality gate."""
    lines_saved = win_end - start + 1
    if not _window_shape_ok(i, j, n, lines_saved, win_blocked):
        return None
    reads = win_loads | win_aug
    live_in_set = {nm for nm in reads if nm in params_and_prior}
    defined = (win_raw - win_comp) | win_aug
    read_after = defined & suffix_loads[j]
    # A name read after the window but assigned only CONDITIONALLY inside it (not
    # in ``win_definite``): if it PRE-EXISTS it is threaded through as an extra
    # param (bound on entry, so a sound return); if it does NOT pre-exist the
    # helper would ``return`` a maybe-unbound value — never SUGGEST such a seam
    # (the planner refuses it too). The suggester side of the packaging.licenses
    # fix.
    conditional = read_after - win_definite
    if conditional - params_and_prior:
        return None
    live_in = sorted(live_in_set | (conditional & params_and_prior))
    if len(live_in) > _SUGGEST_MAX_PARAMS:
        return None
    live_out = sorted(read_after)
    if len(live_out) > _SUGGEST_MAX_RETURNS:
        return None
    # Favor a big body behind a small interface (few params/returns).
    score = lines_saved - 2 * (len(live_in) + len(live_out))
    return {
        "function": fn.name,
        "line": fn.lineno,
        "start": start,
        "end": win_end,
        "name": _suggest_helper_name(fn.name),
        "params": live_in,
        "returns": live_out,
        "lines_saved": lines_saved,
        "_score": score,
    }


def suggest_extractions(source: str, tree: ast.Module | None = None) -> list[dict]:
    """For each long, closure-free function, the single best contiguous run to
    extract — the seam with the most lines saved for the smallest interface.

    ``tree`` lets a caller that already parsed ``source`` (Apex's
    mtime-fingerprinted source index) hand the parse in, skipping the re-parse
    this otherwise does on every call. Left ``None`` the source is parsed here
    exactly as before; a supplied ``tree`` must be ``ast.parse(source)``, so the
    seams are identical either way.

    Returns dicts ``{function, line, start, end, name, params, returns,
    lines_saved}`` ready to become an ``apex extract`` command. Read-only and
    deterministic; the suggestion is a proposal, the real apply re-verifies."""
    if tree is None:
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, MemoryError):
            return []
    out: list[dict] = []
    for fn, _container in _iter_closure_free_functions(tree):
        if not _is_minable_function(fn):
            continue
        best = _scan_function(fn)
        if best is not None:
            out.append(best)
    out.sort(key=lambda d: (-d["lines_saved"], d["function"]))
    return out
