"""Inline Function — the inverse of Extract Method.

A tiny single-use helper (``def fee(x): return x * RATE``) read once and called
back through a thin name is rarely a clean abstraction — it's a hop the reader
has to follow. This is the hand that folds it back: EVERY call site of the
helper, project-wide, is replaced by the helper's ``return`` expression with
that call's own arguments substituted in, and the now-dead definition is deleted.

Each call site is bound independently — different sites may pass different
arguments — but the operation is all-or-nothing: if ANY site can't be inlined
safely, the whole plan blocks rather than leave a half-folded helper behind.

Conservative by design — any ambiguity is a **blocker**, never a guess:
  - the function must be defined exactly ONCE across the project;
  - its body must be exactly a single ``return EXPR`` (a leading docstring is
    allowed and ignored) — nothing with statements to relocate;
  - it must not be recursive, carry decorators, or use ``*args`` / ``**kwargs``
    / positional-only (``/``) / keyword-only (``*``) markers (v1 keeps the
    signature shape simple);
  - it must never travel as a bare object (only ever be *called*) — a Name or
    Attribute used outside a Call position means its identity is used, like the
    ``object_refs`` guard in ``ProjectProfiler._scan_dead_params``;
  - there must be at least ONE call site (zero → "nothing to inline");
  - PER call site: it must pass only plain positional/keyword arguments (no
    ``*`` / ``**`` unpacking), supply every required parameter, and not name a
    keyword that isn't a parameter;
  - PER call site: a parameter used more than once whose argument isn't a "pure
    simple" expression blocks the WHOLE operation — inlining would duplicate a
    side-effecting evaluation; the offending site is named.

The substitution is done by source-span splicing inside the helper's own
``return`` text (never an ``ast.unparse`` round-trip), so the original spelling
and formatting survive — exactly like the rest of the refactor family. Several
call sites and/or the definition may live in the same file; edits within a file
are applied bottom-up (highest line first) to keep line numbers valid, and edits
across files ride the per-file ``new_contents`` as before. Every changed file
must re-parse or the plan blocks rather than write something broken.

Apply is suite-verified with automatic rollback via :class:`RenamePlan` /
``apply_rename``. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _py_files

__all__ = ["plan_inline", "suggest_inlines"]


def _segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def _return_expr(fn: ast.FunctionDef) -> ast.expr | None:
    """The single ``return EXPR`` value of ``fn``, ignoring a leading docstring.
    None when the body isn't exactly one return of a value."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None
    return body[0].value


def _simple_params(fn: ast.FunctionDef) -> bool:
    """True only for a signature of regular positional-or-keyword params (with
    or without defaults) — no ``*args``/``**kwargs``/posonly/kwonly markers."""
    a = fn.args
    return not (a.vararg or a.kwarg or a.posonlyargs or a.kwonlyargs)


def _is_pure_simple(node: ast.expr) -> bool:
    """A Name, a Constant, or an Attribute chain over those — re-evaluating it
    has no observable side effect, so it is safe to duplicate."""
    if isinstance(node, (ast.Name, ast.Constant)):
        return True
    if isinstance(node, ast.Attribute):
        return _is_pure_simple(node.value)
    return False


def _call_sites(trees: dict[str, ast.Module], func_name: str) -> list[tuple[str, ast.Call]]:
    """Every ``func_name(...)`` call, project-wide (bare-Name callee only — the
    object-reference guard already forbids it travelling under any other form)."""
    out: list[tuple[str, ast.Call]] = []
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == func_name:
                out.append((rel, node))
    return out


def _call_site_counts(trees: dict[str, ast.Module]) -> dict[str, int]:
    """How many bare-Name ``NAME(...)`` calls each name has, project-wide, in ONE
    walk. ``_call_site_counts(trees)[name]`` equals ``len(_call_sites(trees,
    name))`` — the suggester only needs the COUNT, so it reads it from this map
    instead of re-walking every tree per candidate (the same O(names × nodes) →
    O(nodes) collapse as the bare-object set)."""
    counts: dict[str, int] = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                counts[node.func.id] = counts.get(node.func.id, 0) + 1
    return counts


def _has_object_ref(trees: dict[str, ast.Module], func_name: str) -> bool:
    """True if ``func_name`` is ever used as a bare object (Name/Attribute
    outside a Call's callee position) — its identity is used, so we can't inline.
    Mirrors ``ProjectProfiler._scan_dead_params``'s ``object_refs`` logic."""
    for tree in trees.values():
        call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == func_name \
                    and id(node) not in call_funcs and not isinstance(node.ctx, ast.Store):
                return True
            if isinstance(node, ast.Attribute) and node.attr == func_name \
                    and id(node) not in call_funcs:
                return True
    return False


def _bare_object_names(trees: dict[str, ast.Module]) -> set[str]:
    """Every name used as a bare object (Name/Attribute outside a Call's callee
    position) ANYWHERE in ``trees`` — the whole-project complement of
    :func:`_has_object_ref`, computed in ONE walk instead of one per candidate.

    ``name in _bare_object_names(trees)`` is exactly ``_has_object_ref(trees,
    name)``: each tree's Call-func node ids are gathered once, then every bare
    Name/Attribute contributes its name to the set under the identical guard
    (Store-context Names are excluded). A project-wide scan that previously
    re-walked all trees per candidate (O(names × nodes)) becomes a single
    O(nodes) pass — the difference between minutes and seconds on a large repo."""
    bare: set[str] = set()
    for tree in trees.values():
        call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and id(node) not in call_funcs \
                    and not isinstance(node.ctx, ast.Store):
                bare.add(node.id)
            elif isinstance(node, ast.Attribute) and id(node) not in call_funcs:
                bare.add(node.attr)
    return bare


def _bare_and_call_index(
        trees: dict[str, ast.Module]) -> tuple[set[str], dict[str, int]]:
    """The bare-object set AND the bare-Name call-site counts in ONE walk/tree.

    Returns ``(bare, counts)`` byte-for-byte equal to ``(_bare_object_names(
    trees), _call_site_counts(trees))`` — identical membership, identical integer
    counts — but folds their THREE whole-project ``ast.walk`` passes per tree
    (two inside ``_bare_object_names`` for callee ids + the bare scan, one inside
    ``_call_site_counts``) down to a SINGLE pass.

    The collapse is sound because ``ast.walk`` is breadth-first over a deque: a
    node is yielded *before* its own children are enqueued, so every ``Call`` is
    seen strictly before its ``.func`` callee. Recording ``id(call.func)`` the
    moment the Call is visited therefore guarantees the callee id is already in
    ``call_funcs`` by the time that Name/Attribute is itself yielded — so the
    very same callee-exclusion guard the two-walk form applies still holds with
    one walk. The standalone helpers remain the characterized reference; this is
    purely the suggester's hoisted, de-duplicated version of running both."""
    bare: set[str] = set()
    counts: dict[str, int] = {}
    for tree in trees.values():
        call_funcs: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                call_funcs.add(id(func))
                if isinstance(func, ast.Name):
                    counts[func.id] = counts.get(func.id, 0) + 1
            elif isinstance(node, ast.Name) and id(node) not in call_funcs \
                    and not isinstance(node.ctx, ast.Store):
                bare.add(node.id)
            elif isinstance(node, ast.Attribute) and id(node) not in call_funcs:
                bare.add(node.attr)
    return bare, counts


def _bind_arguments(plan: RenamePlan, source: str, fn: ast.FunctionDef,
                    call: ast.Call, site: str) -> dict[str, str] | None:
    """Map each parameter name → its argument SOURCE TEXT for this call: by
    position, then by keyword, falling back to the parameter's default. Blocks
    (returns None) on a missing required argument or unknown keyword. ``site``
    is a ``rel:line`` label woven into any blocker message."""
    params = list(fn.args.args)
    defaults = list(fn.args.defaults)
    # Right-aligned defaults: the last len(defaults) params have one.
    default_for: dict[str, ast.expr] = {}
    for p, d in zip(params[len(params) - len(defaults):], defaults):
        default_for[p.arg] = d

    param_names = {p.arg for p in params}
    bound: dict[str, str] = {}
    if len(call.args) > len(params):
        plan.blockers.append(
            f"{site}: call site passes {len(call.args)} positional args but "
            f"{plan.old}() takes {len(params)}")
        return None
    for p, arg in zip(params, call.args):
        bound[p.arg] = _segment(source, arg)
    kw_by_name = {kw.arg: kw for kw in call.keywords}
    for name in kw_by_name:
        if name not in param_names:
            plan.blockers.append(
                f"{site}: call site passes keyword '{name}' which is not a "
                f"parameter of {plan.old}()")
            return None
    for p in params:
        if p.arg in bound:
            continue
        if p.arg in kw_by_name:
            bound[p.arg] = _segment(source, kw_by_name[p.arg].value)
        elif p.arg in default_for:
            # The default lives in the DEFINING module's source.
            bound[p.arg] = ast.get_source_segment(
                plan.new_contents.get(plan.defined_in, source), default_for[p.arg]) \
                or _segment(source, default_for[p.arg])
        else:
            plan.blockers.append(
                f"{site}: call site does not supply required parameter "
                f"'{p.arg}'")
            return None
    return bound


def _substitute(expr_text: str, expr: ast.expr, params: set[str],
                bound: dict[str, str], arg_nodes: dict[str, ast.expr],
                plan: RenamePlan, site: str) -> str | None:
    """Splice ``(arg_text)`` over every Name in EXPR that names a parameter.
    Spans are processed right-to-left so earlier offsets stay valid. Returns the
    rewritten EXPR text, or None after recording a side-effect blocker naming
    ``site``."""
    # Count parameter uses to gate the side-effect-duplication rule.
    uses: dict[str, list[ast.Name]] = {p: [] for p in params}
    for n in ast.walk(expr):
        if isinstance(n, ast.Name) and n.id in params and isinstance(n.ctx, ast.Load):
            uses[n.id].append(n)
    for name, nodes in uses.items():
        if len(nodes) > 1 and name in arg_nodes and not _is_pure_simple(arg_nodes[name]):
            plan.blockers.append(
                f"{site}: parameter '{name}' is used {len(nodes)} times and its "
                "argument isn't a pure simple expression — inlining would "
                "duplicate a side-effecting evaluation")
            return None

    base_line = expr.lineno
    base_col = expr.col_offset
    lines = expr_text.splitlines(keepends=True)
    line_starts = [0]
    for ln in lines:
        line_starts.append(line_starts[-1] + len(ln))

    def to_offset(line: int, col: int) -> int:
        # node positions are file-absolute; rebase onto EXPR's own text.
        rel_line = line - base_line
        if rel_line == 0:
            return col - base_col
        return line_starts[rel_line] + col

    spans: list[tuple[int, int, str]] = []  # (start, end, replacement)
    for nodes in uses.values():
        for n in nodes:
            start = to_offset(n.lineno, n.col_offset)
            end = to_offset(n.end_lineno, n.end_col_offset)
            spans.append((start, end, f"({bound[n.id]})"))

    out = expr_text
    for start, end, repl in sorted(spans, reverse=True):
        out = out[:start] + repl + out[end:]
    return out


def _delete_def_lines(lines: list[str], fn: ast.FunctionDef) -> list[str]:
    """Drop the full ``def`` line span (def line through ``end_lineno``) and one
    trailing blank line if present. Returns the new line list."""
    lo = fn.lineno - 1
    hi = fn.end_lineno
    if hi < len(lines) and lines[hi].strip() == "":
        hi += 1
    return lines[:lo] + lines[hi:]


def _parse_project(
        project_root: str | Path) -> tuple[dict[str, str], dict[str, ast.Module]]:
    """Read every ``*.py`` file under ``project_root`` and return ``(sources,
    trees)``: the raw text per rel-path and the parse for each file that parses
    (unparseable files are dropped from ``trees`` but kept in ``sources``)."""
    files = _py_files(Path(project_root))
    sources = dict(files)
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError:
            continue
    return sources, trees


def _resolve_definition(
        plan: RenamePlan, trees: dict[str, ast.Module],
        function_name: str) -> ast.FunctionDef | None:
    """Find the single top-level ``def function_name`` across ``trees``, setting
    ``plan.defined_in``. Records a blocker and returns None when it isn't defined
    exactly once at top level."""
    definitions = [
        (rel, node) for rel, tree in trees.items() for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name]
    if len(definitions) != 1:
        plan.blockers.append(
            f"'{function_name}' must be defined exactly once at top level "
            f"(found {len(definitions)})")
        return None
    defmod, fn = definitions[0]
    plan.defined_in = defmod
    return fn


def _qualify_definition(
        plan: RenamePlan, trees: dict[str, ast.Module], fn: ast.FunctionDef,
        function_name: str) -> ast.expr | None:
    """Run the helper-level qualification rules (no decorators, simple params,
    single ``return EXPR`` body, non-recursive, never a bare object) and return
    the return EXPR when all pass. Records the matching blocker and returns None
    on the first failure."""
    if fn.decorator_list:
        plan.blockers.append(f"'{function_name}' has decorators — not inlinable")
        return None
    if not _simple_params(fn):
        plan.blockers.append(
            f"'{function_name}' uses *args/**kwargs/positional-only/keyword-only "
            "parameters — not supported in v1")
        return None
    expr = _return_expr(fn)
    if expr is None:
        plan.blockers.append(
            f"'{function_name}' body is not a single `return EXPR` "
            "(only a return — optionally after a docstring — can be inlined)")
        return None
    if any(isinstance(n, ast.Name) and n.id == function_name for n in ast.walk(expr)):
        plan.blockers.append(f"'{function_name}' is recursive — not inlinable")
        return None
    if _has_object_ref(trees, function_name):
        plan.blockers.append(
            f"'{function_name}' is referenced as a bare object somewhere "
            "(not only called) — its identity is used, so it can't be inlined")
        return None
    return expr


def _arg_nodes_for_call(fn: ast.FunctionDef, call: ast.Call) -> dict[str, ast.expr]:
    """Map each parameter name → its argument EXPR node for this call (positional
    first, then keyword) — the side-effect-duplication gate reads these nodes."""
    arg_nodes: dict[str, ast.expr] = {}
    for p, arg in zip(fn.args.args, call.args):
        arg_nodes[p.arg] = arg
    kw_by_name = {kw.arg: kw for kw in call.keywords}
    for p in fn.args.args:
        if p.arg not in arg_nodes and p.arg in kw_by_name:
            arg_nodes[p.arg] = kw_by_name[p.arg].value
    return arg_nodes


def _resolve_call_site(
        plan: RenamePlan, sources: dict[str, str], fn: ast.FunctionDef,
        expr: ast.expr, expr_text: str, params: set[str], call_rel: str,
        call: ast.Call) -> tuple[int, int, int, str] | None:
    """Resolve ONE call site into an intra-line splice tuple ``(lineno, col,
    end_col, text)``, or None after recording the first blocker (unpacking,
    binding failure, side-effect duplication, or a multi-line call span)."""
    site = f"{call_rel}:{call.lineno}"
    call_source = sources[call_rel]

    if any(isinstance(a, ast.Starred) for a in call.args) \
            or any(kw.arg is None for kw in call.keywords):
        plan.blockers.append(
            f"{site}: the call site uses * or ** unpacking — only plain "
            "positional/keyword arguments can be inlined")
        return None

    bound = _bind_arguments(plan, call_source, fn, call, site)
    if bound is None:
        return None

    arg_nodes = _arg_nodes_for_call(fn, call)
    substituted = _substitute(expr_text, expr, params, bound, arg_nodes,
                              plan, site)
    if substituted is None:
        return None
    inlined = f"({substituted})"

    # The call span must be a single-line intra-line edit (like pattern_rewrite).
    if call.lineno != call.end_lineno:
        plan.blockers.append(
            f"{site}: the call spans multiple lines — "
            "collapse it onto one line first")
        return None

    return (call.lineno, call.col_offset, call.end_col_offset, inlined)


def _resolve_all_sites(
        plan: RenamePlan, sources: dict[str, str], fn: ast.FunctionDef,
        expr: ast.expr, params: set[str], expr_text: str,
        sites: list[tuple[str, ast.Call]]
) -> dict[str, list[tuple[int, int, int, str]]] | None:
    """Resolve EVERY call site independently into intra-line splice edits. The
    operation is all-or-nothing: any unsafe/unresolvable site blocks the whole
    plan (returns None), so existing call sites are never left half-folded.
    ``call_edits[rel]`` is a list of ``(call_lineno, col, end_col, text)``."""
    call_edits: dict[str, list[tuple[int, int, int, str]]] = {}
    for call_rel, call in sites:
        edit = _resolve_call_site(plan, sources, fn, expr, expr_text, params,
                                  call_rel, call)
        if edit is None:
            return None
        call_edits.setdefault(call_rel, []).append(edit)
    return call_edits


def _apply_file_edits(
        plan: RenamePlan, sources: dict[str, str], fn: ast.FunctionDef,
        defmod: str,
        call_edits: dict[str, list[tuple[int, int, int, str]]]) -> None:
    """Apply call-site splices and the (single) def deletion file by file, writing
    each touched file's result onto ``plan``. Within a file everything is applied
    bottom-up (highest line first) so earlier line/column indices stay valid;
    edits across files ride independent ``new_contents`` entries."""
    files_touched = set(call_edits) | {defmod}
    for rel in files_touched:
        source = sources[rel]
        lines = source.splitlines(keepends=True)
        edits = sorted(call_edits.get(rel, []), key=lambda e: (e[0], e[1]),
                       reverse=True)
        delete_here = rel == defmod
        n_edits = len(call_edits.get(rel, [])) + (1 if delete_here else 0)

        # Bottom-up: process whichever sits lower in the file first. The def
        # deletion removes whole lines above-or-below; a deletion below a splice
        # leaves that splice's line index untouched, and we apply splices that
        # sit above the def before the deletion runs.
        below_def = [e for e in edits if e[0] > fn.lineno]
        above_def = [e for e in edits if e[0] <= fn.lineno]
        for lineno, col, end_col, text in below_def:
            row = lines[lineno - 1]
            lines[lineno - 1] = row[:col] + text + row[end_col:]
        if delete_here:
            lines = _delete_def_lines(lines, fn)
        for lineno, col, end_col, text in above_def:
            row = lines[lineno - 1]
            lines[lineno - 1] = row[:col] + text + row[end_col:]

        plan.originals[rel] = source
        plan.new_contents[rel] = "".join(lines)
        plan.edits_by_file[rel] = n_edits


def _verify_parses(plan: RenamePlan) -> None:
    """Re-parse every file the plan would write; on the first SyntaxError record a
    blocker and clear the plan's pending writes so nothing broken is emitted."""
    for rel, content in plan.new_contents.items():
        try:
            ast.parse(content)
        except SyntaxError as e:
            plan.blockers.append(
                f"inlining would not parse ({e}) in {rel} — refusing to write")
            plan.new_contents.clear()
            plan.originals.clear()
            plan.edits_by_file.clear()
            return


def plan_inline(project_root: str | Path, function_name: str) -> RenamePlan:
    """Build the single-call-site inline plan for ``function_name``, or block."""
    plan = RenamePlan(old=function_name, new="")
    sources, trees = _parse_project(project_root)

    fn = _resolve_definition(plan, trees, function_name)
    if fn is None:
        return plan
    expr = _qualify_definition(plan, trees, fn, function_name)
    if expr is None:
        return plan

    sites = _call_sites(trees, function_name)
    if not sites:
        plan.blockers.append(f"no call site for '{function_name}' — nothing to inline")
        return plan

    params = {p.arg for p in fn.args.args}
    expr_text = _segment(sources[plan.defined_in], expr)

    call_edits = _resolve_all_sites(plan, sources, fn, expr, params, expr_text, sites)
    if call_edits is None:
        return plan

    _apply_file_edits(plan, sources, fn, plan.defined_in, call_edits)
    _verify_parses(plan)
    return plan


# ── Suggestion: which helpers would `apex inline` cleanly accept? ──
# A near-single-use helper is the strongest inline candidate; many call sites
# would bloat code, so the scan caps the call-site count low.
_SUGGEST_MAX_CALL_SITES = 2


def _suggest_trees(
        project_root: str | Path,
        trees: dict[str, ast.Module] | None) -> dict[str, ast.Module]:
    """The parses ``suggest_inlines`` will scan: the caller-supplied ``trees``
    untouched, or — when None — read+parse every ``*.py`` from disk, dropping
    files that don't parse (exactly the old inline fallback)."""
    if trees is not None:
        return trees
    parsed: dict[str, ast.Module] = {}
    for rel, text in _py_files(Path(project_root)):
        try:
            parsed[rel] = ast.parse(text)
        except SyntaxError:
            continue
    return parsed


def _defs_by_name(
        trees: dict[str, ast.Module]) -> dict[str, list[tuple[str, ast.FunctionDef]]]:
    """name → list of ``(module, FunctionDef)`` for every top-level def, modules
    visited in sorted order so the per-name lists are deterministic. Names with a
    single entry are the only inline candidates."""
    defs_by_name: dict[str, list[tuple[str, ast.FunctionDef]]] = {}
    for rel in sorted(trees):
        for node in trees[rel].body:
            if isinstance(node, ast.FunctionDef):
                defs_by_name.setdefault(node.name, []).append((rel, node))
    return defs_by_name


def _suggest_qualifies(
        name: str, fn: ast.FunctionDef, bare: set[str], n_sites: int) -> bool:
    """The lightweight structural mirror of ``plan_inline``'s qualification rules
    for ONE single-definition helper: no decorators, simple params, a single
    ``return EXPR`` body, non-recursive, never a bare object, and a SMALL call
    count (1..``_SUGGEST_MAX_CALL_SITES``). True only when every rule passes."""
    if fn.decorator_list or not _simple_params(fn):
        return False
    expr = _return_expr(fn)
    if expr is None:
        return False
    # Non-recursive: the body must not call back to its own name.
    if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(expr)):
        return False
    # Never travels as a bare object — only ever called.
    if name in bare:
        return False
    return 1 <= n_sites <= _SUGGEST_MAX_CALL_SITES


def suggest_inlines(project_root: str | Path,
                    trees: dict[str, ast.Module] | None = None) -> list[dict]:
    """Project-level scan for tiny single-use helpers ``apex inline`` would
    cleanly accept, made into a concrete ``apex inline FUNC`` command.

    Conservative by construction — each rule is one of ``plan_inline``'s
    qualification rules, applied here as a lightweight structural check (no
    per-function ``plan_inline`` round-trip). A function qualifies only when it
    is defined exactly ONCE project-wide, its body is a single ``return EXPR``
    (an optional leading docstring is ignored), it is non-recursive, carries no
    decorators, uses only regular positional-or-keyword params (no
    ``*args``/``**kwargs``/posonly/kwonly), is NEVER referenced as a bare object
    (only ever called — the ``object_refs`` guard from
    ``ProjectProfiler._scan_dead_params``), and has a SMALL number of call sites
    (1 or 2). When unsure, it doesn't suggest.

    ``trees`` lets a caller that already parsed the project once (Apex's
    mtime-fingerprinted source index) hand the parses straight in, skipping the
    re-walk + re-parse of every module; left ``None`` it reads and parses from
    disk exactly as before, so every existing caller is unchanged.

    Returns a deterministic, sorted list of ``{module, function, line,
    call_sites}`` dicts. Read-only and stdlib-only; the suggestion is a
    proposal, the real ``plan_inline`` re-verifies."""
    trees = _suggest_trees(project_root, trees)
    defs_by_name = _defs_by_name(trees)

    # The bare-object guard and the call-site count are both whole-project and
    # name-independent, so compute each ONCE rather than re-walking every tree
    # per candidate: `name in bare` is exactly `_has_object_ref(trees, name)`,
    # and `call_counts.get(name, 0)` is exactly `len(_call_sites(trees, name))`.
    # `_bare_and_call_index` produces both in a single shared scan (two walks per
    # tree instead of the three the two standalone helpers would do), so the
    # result is identical while the hottest part of the scan runs once less.
    bare, call_counts = _bare_and_call_index(trees)

    found: list[dict] = []
    for name in sorted(defs_by_name):
        defs = defs_by_name[name]
        if len(defs) != 1:
            continue
        rel, fn = defs[0]
        n_sites = call_counts.get(name, 0)
        if not _suggest_qualifies(name, fn, bare, n_sites):
            continue
        found.append({"module": rel, "function": name,
                      "line": fn.lineno, "call_sites": n_sites})
    # Fewest call sites first (strongest candidate), then module then function.
    found.sort(key=lambda d: (d["call_sites"], d["module"], d["function"]))
    return found
