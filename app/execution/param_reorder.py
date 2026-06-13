"""Reorder a function's parameters — the signature family's fourth operation.

Changes the order of the REGULAR positional parameters of a top-level
function. Call sites need no edit by construction: the operation only
proceeds when every caller passes those parameters as keywords (keyword
arguments don't care about order) — a positional caller blocks with the
chain hint ("run `apex signature keywordify` first").

Scope is deliberately narrow, each exclusion a real hazard:

  - positional-only parameters (before ``/``) keep their order — their
    position IS their API;
  - ``*args`` / keyword-only / ``**kwargs`` sections stay where they are;
  - the new order must be a permutation of the current regular parameters;
  - defaults travel WITH their parameter, and the reordered signature must
    keep required-before-defaulted (or it wouldn't compile);
  - a comment inside the signature blocks (comment-preservation promise).

Reuses :class:`RenamePlan` / :func:`apply_rename` — dry-run diffs, test
verification, rollback. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _py_files
from app.execution.param_drop import _segment, _signature_span
from app.execution.param_rename import _function_defs

__all__ = ["plan_param_reorder"]


def _rebuild_reordered(source: str, fn: ast.FunctionDef | ast.AsyncFunctionDef,
                       order: list[str]) -> str | None:
    """The new ``(...)`` interior with regular params in ``order`` — verbatim
    source segments, defaults attached to their own parameter. None when the
    reorder would put a required parameter after a defaulted one."""
    a = fn.args
    parts: list[str] = []

    def pos_text(arg: ast.arg, default: ast.expr | None) -> str:
        text = _segment(source, arg)
        if default is not None:
            eq = " = " if arg.annotation is not None else "="
            text += f"{eq}{_segment(source, default)}"
        return text

    positional = [*a.posonlyargs, *a.args]
    defaults: list[ast.expr | None] = (
        [None] * (len(positional) - len(a.defaults)) + list(a.defaults))
    by_name = {arg.arg: (arg, defaults[i]) for i, arg in enumerate(positional)}

    for arg in a.posonlyargs:                       # order untouched: API
        parts.append(pos_text(*by_name[arg.arg]))
    if a.posonlyargs:
        parts.append("/")

    seen_default = False
    for name in order:
        arg, default = by_name[name]
        if default is None and seen_default:
            return None  # required after defaulted — wouldn't compile
        seen_default = seen_default or default is not None
        parts.append(pos_text(arg, default))

    if a.vararg:
        parts.append(f"*{_segment(source, a.vararg)}")
    elif a.kwonlyargs:
        parts.append("*")
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        text = _segment(source, arg)
        if default is not None:
            eq = " = " if arg.annotation is not None else "="
            text += f"{eq}{_segment(source, default)}"
        parts.append(text)
    if a.kwarg:
        parts.append(f"**{_segment(source, a.kwarg)}")
    return ", ".join(parts)


def plan_param_reorder(project_root: str | Path, func_name: str,
                       order: list[str]) -> RenamePlan:
    """Build the reorder plan: def site rebuilt, call sites untouched."""
    plan = RenamePlan(old=func_name, new=func_name)
    root = Path(project_root)
    files = _py_files(root)
    sources = dict(files)
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError:
            continue

    definitions = [(rel, fn) for rel, tree in trees.items()
                   for fn in _function_defs(tree, func_name)]
    if len(definitions) != 1:
        plan.blockers.append(
            f"'{func_name}' must be defined exactly once at top level "
            f"(found {len(definitions)})")
        return plan
    defmod, fn = definitions[0]
    plan.defined_in = defmod
    dotted = defmod[:-3].replace("/", ".")
    source = sources[defmod]

    current = [p.arg for p in fn.args.args]
    if sorted(order) != sorted(current):
        plan.blockers.append(
            f"the new order must be a permutation of {func_name}()'s regular "
            f"parameters ({', '.join(current) or 'none'})")
        return plan
    if order == current:
        plan.blockers.append("the requested order is already the current order")
        return plan

    span = _signature_span(source, fn)
    if span is None:
        plan.blockers.append(f"{defmod}: could not pin the signature span")
        return plan
    sl, sc, el, ec = span
    src_lines = source.splitlines(keepends=True)
    sig_text = (
        src_lines[sl - 1][sc:ec] if sl == el
        else src_lines[sl - 1][sc:] + "".join(src_lines[sl:el - 1]) + src_lines[el - 1][:ec])
    if "#" in sig_text:
        plan.blockers.append(
            f"{defmod}: the signature block contains a comment — rebuilding "
            "it would drop the comment, so this stays a human edit")
        return plan

    new_inner = _rebuild_reordered(source, fn, order)
    if new_inner is None:
        plan.blockers.append(
            "the reorder would put a required parameter after a defaulted "
            "one — that signature wouldn't compile")
        return plan

    # Every caller must already pass the regular params as keywords: a
    # positional argument beyond the positional-only prefix would silently
    # re-bind to a DIFFERENT parameter after the reorder.
    n_posonly = len(fn.args.posonlyargs)
    for rel, tree in trees.items():
        from_names: set[str] = {func_name} if rel == defmod else set()
        module_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == dotted:
                for alias in node.names:
                    if alias.name == func_name:
                        from_names.add(alias.asname or func_name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == dotted:
                        module_aliases.add(alias.asname or alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            is_ours = (isinstance(f, ast.Name) and f.id in from_names) or (
                isinstance(f, ast.Attribute) and f.attr == func_name
                and ast.unparse(f.value) in module_aliases)
            if is_ours and len(node.args) > n_posonly:
                plan.blockers.append(
                    f"{rel}:{node.lineno}: passes reordered parameters "
                    "POSITIONALLY — run `apex signature keywordify "
                    f"{func_name}` first, then re-run")
    if plan.blockers:
        return plan

    new_def = src_lines[sl - 1][:sc] + f"({new_inner})" + src_lines[el - 1][ec:]
    plan.originals[defmod] = source
    plan.new_contents[defmod] = "".join([*src_lines[:sl - 1], new_def, *src_lines[el:]])
    plan.edits_by_file[defmod] = 1
    return plan
