"""Inline Function — the inverse of Extract Method.

A tiny single-use helper (``def fee(x): return x * RATE``) read once and called
once is rarely a clean abstraction — it's a hop the reader has to follow. This
is the hand that folds it back: the single call site is replaced by the helper's
``return`` expression with the call's arguments substituted in, and the now-dead
definition is deleted.

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
  - there must be exactly ONE call site (zero → "nothing to inline", more than
    one → out of scope for v1);
  - the call must pass only plain positional/keyword arguments (no ``*`` / ``**``
    unpacking);
  - a parameter used more than once whose argument isn't a "pure simple"
    expression blocks — inlining would duplicate a side-effecting evaluation.

The substitution is done by source-span splicing inside the helper's own
``return`` text (never an ``ast.unparse`` round-trip), so the original spelling
and formatting survive — exactly like the rest of the refactor family. Edits at
the call site and the deletion of the definition may live in the same file, so
they are applied bottom-up to keep line numbers valid. The result must re-parse
or the plan blocks rather than write something broken.

Apply is suite-verified with automatic rollback via :class:`RenamePlan` /
``apply_rename``. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _py_files

__all__ = ["plan_inline"]


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
    if a.vararg or a.kwarg or a.posonlyargs or a.kwonlyargs:
        return False
    return True


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


def _bind_arguments(plan: RenamePlan, source: str, fn: ast.FunctionDef,
                    call: ast.Call) -> dict[str, str] | None:
    """Map each parameter name → its argument SOURCE TEXT for this call: by
    position, then by keyword, falling back to the parameter's default. Blocks
    (returns None) on a missing required argument."""
    params = list(fn.args.args)
    defaults = list(fn.args.defaults)
    # Right-aligned defaults: the last len(defaults) params have one.
    default_for: dict[str, ast.expr] = {}
    for p, d in zip(params[len(params) - len(defaults):], defaults):
        default_for[p.arg] = d

    bound: dict[str, str] = {}
    if len(call.args) > len(params):
        plan.blockers.append(
            f"call site passes {len(call.args)} positional args but "
            f"{plan.old}() takes {len(params)}")
        return None
    for p, arg in zip(params, call.args):
        bound[p.arg] = _segment(source, arg)
    kw_by_name = {kw.arg: kw for kw in call.keywords}
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
                f"call site does not supply required parameter '{p.arg}'")
            return None
    return bound


def _substitute(expr_text: str, expr: ast.expr, params: set[str],
                bound: dict[str, str], arg_nodes: dict[str, ast.expr],
                plan: RenamePlan) -> str | None:
    """Splice ``(arg_text)`` over every Name in EXPR that names a parameter.
    Spans are processed right-to-left so earlier offsets stay valid. Returns the
    rewritten EXPR text, or None after recording a side-effect blocker."""
    # Count parameter uses to gate the side-effect-duplication rule.
    uses: dict[str, list[ast.Name]] = {p: [] for p in params}
    for n in ast.walk(expr):
        if isinstance(n, ast.Name) and n.id in params and isinstance(n.ctx, ast.Load):
            uses[n.id].append(n)
    for name, nodes in uses.items():
        if len(nodes) > 1 and name in arg_nodes and not _is_pure_simple(arg_nodes[name]):
            plan.blockers.append(
                f"parameter '{name}' is used {len(nodes)} times and its argument "
                "isn't a pure simple expression — inlining would duplicate a "
                "side-effecting evaluation")
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


def plan_inline(project_root: str | Path, function_name: str) -> RenamePlan:
    """Build the single-call-site inline plan for ``function_name``, or block."""
    plan = RenamePlan(old=function_name, new="")
    root = Path(project_root)
    files = _py_files(root)
    sources = dict(files)
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError:
            continue

    definitions = [
        (rel, node) for rel, tree in trees.items() for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name]
    if len(definitions) != 1:
        plan.blockers.append(
            f"'{function_name}' must be defined exactly once at top level "
            f"(found {len(definitions)})")
        return plan
    defmod, fn = definitions[0]
    plan.defined_in = defmod
    def_source = sources[defmod]

    if fn.decorator_list:
        plan.blockers.append(f"'{function_name}' has decorators — not inlinable")
        return plan
    if not _simple_params(fn):
        plan.blockers.append(
            f"'{function_name}' uses *args/**kwargs/positional-only/keyword-only "
            "parameters — not supported in v1")
        return plan
    expr = _return_expr(fn)
    if expr is None:
        plan.blockers.append(
            f"'{function_name}' body is not a single `return EXPR` "
            "(only a return — optionally after a docstring — can be inlined)")
        return plan
    if any(isinstance(n, ast.Name) and n.id == function_name for n in ast.walk(expr)):
        plan.blockers.append(f"'{function_name}' is recursive — not inlinable")
        return plan
    if _has_object_ref(trees, function_name):
        plan.blockers.append(
            f"'{function_name}' is referenced as a bare object somewhere "
            "(not only called) — its identity is used, so it can't be inlined")
        return plan

    sites = _call_sites(trees, function_name)
    if not sites:
        plan.blockers.append(f"no call site for '{function_name}' — nothing to inline")
        return plan
    if len(sites) > 1:
        where = ", ".join(f"{rel}:{c.lineno}" for rel, c in sites)
        plan.blockers.append(
            f"'{function_name}' has {len(sites)} call sites ({where}) — "
            "inline supports a single call site in v1")
        return plan
    call_rel, call = sites[0]
    call_source = sources[call_rel]

    if any(isinstance(a, ast.Starred) for a in call.args) \
            or any(kw.arg is None for kw in call.keywords):
        plan.blockers.append(
            "the call site uses * or ** unpacking — only plain positional/"
            "keyword arguments can be inlined")
        return plan

    bound = _bind_arguments(plan, call_source, fn, call)
    if bound is None:
        return plan

    params = {p.arg for p in fn.args.args}
    arg_nodes: dict[str, ast.expr] = {}
    for p, arg in zip(fn.args.args, call.args):
        arg_nodes[p.arg] = arg
    kw_by_name = {kw.arg: kw for kw in call.keywords}
    for p in fn.args.args:
        if p.arg not in arg_nodes and p.arg in kw_by_name:
            arg_nodes[p.arg] = kw_by_name[p.arg].value

    expr_text = _segment(def_source, expr)
    substituted = _substitute(expr_text, expr, params, bound, arg_nodes, plan)
    if substituted is None:
        return plan
    inlined = f"({substituted})"

    # The call span must be a single-line intra-line edit (like pattern_rewrite).
    if call.lineno != call.end_lineno:
        plan.blockers.append(
            f"{call_rel}:{call.lineno}: the call spans multiple lines — "
            "collapse it onto one line first")
        return plan

    # Build the new content. The call edit and the def deletion may be in the
    # SAME file; apply bottom-up (higher line numbers first) so indices stay valid.
    same_file = call_rel == defmod
    if same_file:
        lines = call_source.splitlines(keepends=True)
        # Apply the edit that is LOWER in the file first so the other one's line
        # numbers stay valid. If the call is below the def, edit the call first,
        # then delete the (higher) def block. Otherwise delete the def (below the
        # call) first — the call's line index is unaffected by a deletion under it.
        if call.lineno > fn.lineno:
            row = lines[call.lineno - 1]
            lines[call.lineno - 1] = row[:call.col_offset] + inlined + row[call.end_col_offset:]
            lines = _delete_def_lines(lines, fn)
        else:
            lines = _delete_def_lines(lines, fn)
            row = lines[call.lineno - 1]
            lines[call.lineno - 1] = row[:call.col_offset] + inlined + row[call.end_col_offset:]
        plan.originals[call_rel] = call_source
        plan.new_contents[call_rel] = "".join(lines)
        plan.edits_by_file[call_rel] = 2
    else:
        clines = call_source.splitlines(keepends=True)
        row = clines[call.lineno - 1]
        clines[call.lineno - 1] = row[:call.col_offset] + inlined + row[call.end_col_offset:]
        plan.originals[call_rel] = call_source
        plan.new_contents[call_rel] = "".join(clines)
        plan.edits_by_file[call_rel] = 1
        dlines = def_source.splitlines(keepends=True)
        plan.originals[defmod] = def_source
        plan.new_contents[defmod] = "".join(_delete_def_lines(dlines, fn))
        plan.edits_by_file[defmod] = 1

    for rel, content in plan.new_contents.items():
        try:
            ast.parse(content)
        except SyntaxError as e:
            plan.blockers.append(
                f"inlining would not parse ({e}) in {rel} — refusing to write")
            plan.new_contents.clear()
            plan.originals.clear()
            plan.edits_by_file.clear()
            return plan
    return plan
