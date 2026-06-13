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
  - the helper name must be free at module level.

Apply is suite-verified with automatic rollback — exactly like every Apex
change, so even a data-flow corner case can never ship a broken extraction.
Deterministic, stdlib-only; reuses :class:`RenamePlan` / ``apply_rename``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _top_level_bindings

__all__ = ["plan_extract"]

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


def _has_blocking_control(stmts: list, plan: RenamePlan) -> bool:
    """Record a blocker for any relocate-unsafe node in the range."""
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, _NESTED_SCOPE_NODES):
                plan.blockers.append(
                    "the range defines a nested function/lambda — its scope "
                    "can't be analyzed; extract it separately first")
                return True
            if isinstance(n, _CONTROL_NODES):
                kind = type(n).__name__.lower()
                plan.blockers.append(
                    f"the range contains `{kind}` — moving it into a helper "
                    "would change the function's control flow")
                return True
    for stmt in stmts:
        if _has_unenclosed_jump(stmt):
            plan.blockers.append(
                "the range contains a `break`/`continue` whose loop is outside "
                "the selection — it can't be lifted out")
            return True
    return False


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


def plan_extract(project_root: str | Path, file_rel: str,
                 start_line: int, end_line: int, helper_name: str) -> RenamePlan:
    """Build the single-file extract-method plan for ``file_rel``."""
    plan = RenamePlan(old=f"{file_rel}:{start_line}-{end_line}", new=helper_name)
    root = Path(project_root)
    path = root / file_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        plan.blockers.append(f"cannot read {file_rel}")
        return plan

    if not helper_name.isidentifier():
        plan.blockers.append(f"`{helper_name}` is not a valid function name")
        return plan
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        plan.blockers.append(f"{file_rel} doesn't parse: {e}")
        return plan
    if start_line > end_line:
        plan.blockers.append("start line must be <= end line")
        return plan
    if helper_name in _top_level_bindings(tree):
        plan.blockers.append(
            f"`{helper_name}` is already defined at module level — pick another name")
        return plan

    fn, container = _enclosing_function(tree, start_line, end_line)
    if fn is None:
        plan.blockers.append(
            f"lines {start_line}-{end_line} aren't inside one top-level "
            "function/method body (nested-function ranges aren't supported)")
        return plan

    stmts = _selected_statements(fn, start_line, end_line)
    if not stmts:
        plan.blockers.append(
            "the range must cover a contiguous run of complete statements "
            "in the function body (it snaps to statement boundaries)")
        return plan
    if _has_blocking_control(stmts, plan):
        return plan

    before = fn.body[:fn.body.index(stmts[0])]
    after = fn.body[fn.body.index(stmts[-1]) + 1:]

    params_and_prior = _function_param_names(fn) | _stores(before)
    reads = _loads(stmts) | _augmented_targets(stmts)
    live_in = sorted(n for n in reads if n in params_and_prior)

    defined = _stores(stmts) | _augmented_targets(stmts)
    reads_after = _loads(after)
    live_out = sorted(n for n in defined if n in reads_after)

    # Build the helper and the replacement call from the real source text.
    lines = source.splitlines(keepends=True)
    span_lo = stmts[0].lineno
    span_hi = max(getattr(s, "end_lineno", s.lineno) for s in stmts)
    range_lines = lines[span_lo - 1:span_hi]
    base_indent = len(range_lines[0]) - len(range_lines[0].lstrip())
    call_indent = " " * base_indent

    body_lines = _reindent(range_lines, base_indent)
    if live_out:
        body_lines.append("    return " + ", ".join(live_out))
    helper_src = [f"def {helper_name}({', '.join(live_in)}):"] + body_lines
    helper_block = "\n".join(helper_src) + "\n\n\n"

    call_expr = f"{helper_name}({', '.join(live_in)})"
    if live_out:
        call_line = f"{call_indent}{', '.join(live_out)} = {call_expr}\n"
    else:
        call_line = f"{call_indent}{call_expr}\n"

    # Apply edits bottom-up so earlier line numbers stay valid: replace the
    # range first, then insert the helper above the container.
    new_lines = list(lines)
    new_lines[span_lo - 1:span_hi] = [call_line]
    insert_at = min([container.lineno] +
                    [d.lineno for d in getattr(container, "decorator_list", [])]) - 1
    new_lines[insert_at:insert_at] = [helper_block]

    new_source = "".join(new_lines)
    # Sanity: the result must still parse (a malformed extraction is a blocker,
    # not a silent corrupt write).
    try:
        ast.parse(new_source)
    except SyntaxError as e:
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
