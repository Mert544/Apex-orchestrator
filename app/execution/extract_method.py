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

__all__ = ["plan_extract", "suggest_extractions"]

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
    the suggester."""
    params_and_prior = _function_param_names(fn) | _stores(before)
    reads = _loads(stmts) | _augmented_targets(stmts)
    live_in = sorted(n for n in reads if n in params_and_prior)

    defined = _stores(stmts) | _augmented_targets(stmts)
    reads_after = _loads(after)
    live_out = sorted(n for n in defined if n in reads_after)
    return live_in, live_out


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

    __slots__ = ("loads", "aug", "raw_stores", "comp", "blocks")

    def __init__(self, stmt) -> None:
        loads: set[str] = set()
        aug: set[str] = set()
        raw_stores: set[str] = set()
        comp: set[str] = set()
        blocks = False
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name):
                ctx = n.ctx
                if isinstance(ctx, ast.Load):
                    loads.add(n.id)
                elif isinstance(ctx, ast.Store):
                    raw_stores.add(n.id)
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                aug.add(n.target.id)
            elif isinstance(n, _COMP_NODES):
                for gen in n.generators:
                    for t in ast.walk(gen.target):
                        if isinstance(t, ast.Name):
                            comp.add(t.id)
            if not blocks and isinstance(n, (*_NESTED_SCOPE_NODES, *_CONTROL_NODES)):
                blocks = True
        # An unenclosed break/continue blocks too — checked once per statement.
        if not blocks and _has_unenclosed_jump(stmt):
            blocks = True
        self.loads = loads
        self.aug = aug
        self.raw_stores = raw_stores
        self.comp = comp
        self.blocks = blocks


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
    live_in, live_out = _data_flow(fn, before, stmts, after)

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

    best: tuple[int, dict] | None = None
    for i in range(n):
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
    win_end = 0
    win_blocked = False
    for j in range(i + 1, n + 1):
        f = facts[j - 1]
        win_loads |= f.loads
        win_aug |= f.aug
        win_raw |= f.raw_stores
        win_comp |= f.comp
        if line_hi[j - 1] > win_end:
            win_end = line_hi[j - 1]
        if f.blocks:
            win_blocked = True
        cand = _window_candidate(fn, i, j, n, start, win_end, win_blocked,
                                 win_loads, win_aug, win_raw, win_comp,
                                 params_and_prior, suffix_loads)
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


def _window_candidate(fn, i: int, j: int, n: int, start: int, win_end: int,
                      win_blocked: bool, win_loads: set[str], win_aug: set[str],
                      win_raw: set[str], win_comp: set[str],
                      params_and_prior: set[str], suffix_loads: list) -> dict | None:
    """The candidate dict for window ``[i, j)`` (with a private ``_score``), or
    None when the window fails a seam-quality gate."""
    lines_saved = win_end - start + 1
    if not _window_shape_ok(i, j, n, lines_saved, win_blocked):
        return None
    reads = win_loads | win_aug
    live_in = sorted(nm for nm in reads if nm in params_and_prior)
    if len(live_in) > _SUGGEST_MAX_PARAMS:
        return None
    defined = (win_raw - win_comp) | win_aug
    live_out = sorted(nm for nm in defined if nm in suffix_loads[j])
    if len(live_out) > _SUGGEST_MAX_RETURNS:
        return None
    # Favor a big body behind a small interface (few params/returns).
    score = lines_saved - 2 * (len(live_in) + len(live_out))
    return {
        "function": fn.name,
        "line": fn.lineno,
        "start": start,
        "end": win_end,
        "name": f"_{fn.name}_part",
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
        except SyntaxError:
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
