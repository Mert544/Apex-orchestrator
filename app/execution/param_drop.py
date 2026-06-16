"""Drop an unused parameter — the signature family's second operation.

Removes a parameter that the function body never reads, project-wide: the
``def`` site is rebuilt without it and every call site passing it as a
keyword loses that argument. Same conservative creed as the rest of the
refactor family — every ambiguity is a **blocker**, never a guess:

  - the function must be defined exactly once, at top level;
  - the parameter must be genuinely unused (no read anywhere in the body);
  - a call passing it POSITIONALLY blocks ("convert to keyword first") —
    repositioning other callers' arguments silently is how refactors break
    people;
  - comments inside the signature block (we promise to preserve comments,
    so we refuse the one edit that couldn't);
  - ``f(**kwargs)`` call sites warn — a dict can smuggle the key at runtime.

Reuses :class:`RenamePlan` / :func:`apply_rename`, so dry-run diffs, test
verification and full rollback come for free. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    parse_trees as _parse_trees,
    resolve_sole_definition as _resolve_definition,
)
from app.execution.cross_file_rename import RenamePlan, _py_files
from app.execution.param_rename import _all_params

__all__ = ["plan_param_drop"]


def _signature_span(source: str, fn: ast.FunctionDef | ast.AsyncFunctionDef
                    ) -> tuple[int, int, int, int] | None:
    """(start_line, start_col, end_line, end_col) of the ``(...)`` in the
    header — located by balanced-paren scan from the first ``(`` after the
    function name. None when it can't be pinned."""
    lines = source.splitlines(keepends=True)
    line_i, col = fn.lineno - 1, fn.col_offset
    text = lines[line_i]
    open_col = text.find("(", col)
    if open_col < 0:
        return None
    depth = 0
    li, ci = line_i, open_col
    while li < len(lines):
        row = lines[li]
        while ci < len(row):
            ch = row[ci]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return (line_i + 1, open_col, li + 1, ci + 1)
            ci += 1
        li, ci = li + 1, 0
    return None


def _segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def _param_text(source: str, arg: ast.arg, default: ast.expr | None) -> str:
    """One parameter's verbatim text, defaulted spelling included."""
    text = _segment(source, arg)
    if default is not None:
        # PEP 8: spaces around "=" only when the parameter is annotated.
        eq = " = " if arg.annotation is not None else "="
        text += f"{eq}{_segment(source, default)}"
    return text


def _positional_parts(source: str, a: ast.arguments, drop: str) -> list[str]:
    """Kept positional parameters (with the ``/`` marker when posonly survive),
    defaults right-aligned exactly as Python stores them."""
    positional = [*a.posonlyargs, *a.args]
    defaults: list[ast.expr | None] = (
        [None] * (len(positional) - len(a.defaults)) + list(a.defaults))
    keeps_posonly = any(p.arg != drop for p in a.posonlyargs)
    parts: list[str] = []
    for i, arg in enumerate(positional):
        if arg.arg != drop:
            parts.append(_param_text(source, arg, defaults[i]))
        if keeps_posonly and i == len(a.posonlyargs) - 1:
            parts.append("/")
    return parts


def _keyword_parts(source: str, a: ast.arguments, drop: str) -> list[str]:
    """Kept keyword-only parameters, fronted by the ``*`` marker when any
    survive and no ``*args`` already supplies it."""
    parts: list[str] = []
    if a.vararg:
        parts.append(f"*{_segment(source, a.vararg)}")
    elif a.kwonlyargs and any(k.arg != drop for k in a.kwonlyargs):
        parts.append("*")
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        if arg.arg != drop:
            parts.append(_param_text(source, arg, default))
    if a.kwarg:
        parts.append(f"**{_segment(source, a.kwarg)}")
    return parts


def _rebuild_params(source: str, fn: ast.FunctionDef | ast.AsyncFunctionDef,
                    drop: str) -> str:
    """The new ``(...)`` interior without ``drop`` — each kept parameter's
    text is sliced verbatim from the source, so annotations and defaults
    keep their exact spelling."""
    a = fn.args
    parts = _positional_parts(source, a, drop) + _keyword_parts(source, a, drop)
    return ", ".join(parts)


def _positional_index(fn: ast.FunctionDef | ast.AsyncFunctionDef,
                      name: str) -> int | None:
    """The parameter's index among positionally-fillable params (None when
    it is keyword-only and can never be hit positionally)."""
    positional = [*fn.args.posonlyargs, *fn.args.args]
    for i, arg in enumerate(positional):
        if arg.arg == name:
            return i
    return None


def _validate_droppable(fn: ast.FunctionDef | ast.AsyncFunctionDef,
                        func_name: str, param: str, plan: RenamePlan) -> bool:
    """True when ``param`` is a real, unused, non-vararg parameter; appends
    the matching blocker and returns False otherwise."""
    if param not in [p.arg for p in _all_params(fn)]:
        plan.blockers.append(f"'{param}' is not a parameter of {func_name}()")
        return False
    if (fn.args.vararg and fn.args.vararg.arg == param) or (
            fn.args.kwarg and fn.args.kwarg.arg == param):
        plan.blockers.append(f"'{param}' is *args/**kwargs — not droppable")
        return False
    if any(isinstance(n, ast.Name) and n.id == param for n in ast.walk(fn)):
        plan.blockers.append(
            f"{func_name}() actually READS '{param}' — dropping it would "
            "change behavior, not clean it")
        return False
    return True


def _pin_signature(source: str, fn: ast.FunctionDef | ast.AsyncFunctionDef,
                   defmod: str, plan: RenamePlan
                   ) -> tuple[int, int, int, int] | None:
    """The signature span, or None with a blocker when it can't be pinned or
    the header carries a comment we'd be forced to drop."""
    span = _signature_span(source, fn)
    if span is None:
        plan.blockers.append(f"{defmod}: could not pin the signature span")
        return None
    sl, sc, el, ec = span
    src_lines = source.splitlines(keepends=True)
    sig_text = (
        src_lines[sl - 1][sc:ec] if sl == el
        else src_lines[sl - 1][sc:] + "".join(src_lines[sl:el - 1]) + src_lines[el - 1][:ec])
    if "#" in sig_text:
        plan.blockers.append(
            f"{defmod}: the signature block contains a comment — rebuilding "
            "it would drop the comment, so this stays a human edit")
        return None
    return span


def _call_aliases(tree: ast.Module, rel: str, defmod: str, dotted: str,
                  func_name: str) -> tuple[set[str], set[str]]:
    """The bare names and module aliases under which ``func_name`` is reachable
    in this file: ``(from_names, module_aliases)``."""
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
    return from_names, module_aliases


def _call_targets_func(node: ast.Call, func_name: str, from_names: set[str],
                       module_aliases: set[str]) -> bool:
    """True when this call reaches our function by bare name or by an
    imported module alias."""
    f = node.func
    return (isinstance(f, ast.Name) and f.id in from_names) or (
        isinstance(f, ast.Attribute) and f.attr == func_name
        and ast.unparse(f.value) in module_aliases)


def _keyword_removals(node: ast.Call, rel: str, func_name: str, param: str,
                      plan: RenamePlan) -> list[tuple[int, int, int]]:
    """The intra-line spans for ``param=`` in one call; ``**kwargs`` warns and
    a line-spanning keyword blocks."""
    removals: list[tuple[int, int, int]] = []
    for kw in node.keywords:
        if kw.arg is None:
            plan.warnings.append(
                f"{rel}:{node.lineno}: {func_name}(**…) may still carry "
                f"'{param}' at runtime; check manually")
        elif kw.arg == param:
            if kw.lineno != kw.value.end_lineno:
                plan.blockers.append(
                    f"{rel}:{node.lineno}: '{param}=' spans lines — "
                    "collapse the call first")
                continue
            removals.append((kw.lineno, kw.col_offset,
                             kw.value.end_col_offset))
    return removals


def _collect_removals(tree: ast.Module, rel: str, func_name: str, param: str,
                      pos_index: int | None, from_names: set[str],
                      module_aliases: set[str], plan: RenamePlan
                      ) -> list[tuple[int, int, int]]:
    """The intra-line keyword spans to excise in this file; positional passes
    and line-spanning keywords become blockers, ``**kwargs`` calls warn."""
    removals: list[tuple[int, int, int]] = []  # (line, col_start, col_end)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _call_targets_func(node, func_name, from_names, module_aliases):
            continue
        if pos_index is not None and len(node.args) > pos_index:
            plan.blockers.append(
                f"{rel}:{node.lineno}: passes '{param}' POSITIONALLY — "
                "convert that call to keywords first, then re-run")
            continue
        removals.extend(
            _keyword_removals(node, rel, func_name, param, plan))
    return removals


def _apply_removals(text: str, rel: str, param: str,
                    removals: list[tuple[int, int, int]],
                    plan: RenamePlan) -> str:
    """Excise each keyword span and one separating comma, bottom-up so column
    offsets on the same line never invalidate later edits."""
    lines = text.splitlines(keepends=True)
    for line_no, start, end in sorted(set(removals), reverse=True):
        row = lines[line_no - 1]
        left, right = start, end
        # Eat ONE separating comma: prefer the one before (mid/last
        # argument), else the one after (first argument).
        probe = left - 1
        while probe >= 0 and row[probe] in " \t":
            probe -= 1
        if probe >= 0 and row[probe] == ",":
            left = probe
        else:
            after = right
            while after < len(row) and row[after] in " \t":
                after += 1
            if after < len(row) and row[after] == ",":
                right = after + 1
                while right < len(row) and row[right] == " ":
                    right += 1
            elif not row[:left].strip():
                # The keyword stood alone on its line: its separating
                # comma lives on the line above, out of reach for an
                # intra-line (numbering-safe) edit. The result stays
                # valid (trailing comma) — say so instead of hiding it.
                plan.warnings.append(
                    f"{rel}:{line_no}: dropped a keyword that stood on "
                    "its own line — the call stays valid but ragged; "
                    "run a formatter or tidy by hand")
        lines[line_no - 1] = row[:left] + row[right:]
    return "".join(lines)


def _prune_call_sites(trees: dict[str, ast.Module], sources: dict[str, str],
                      defmod: str, dotted: str, func_name: str, param: str,
                      pos_index: int | None, plan: RenamePlan) -> None:
    """Project-wide keyword pruning. Intra-line edits keep AST line numbers
    valid file-wide, so this safely runs before the def rebuild."""
    for rel, tree in trees.items():
        text = sources[rel]
        from_names, module_aliases = _call_aliases(
            tree, rel, defmod, dotted, func_name)
        removals = _collect_removals(
            tree, rel, func_name, param, pos_index,
            from_names, module_aliases, plan)
        if plan.blockers:
            continue
        if removals:
            text = _apply_removals(text, rel, param, removals, plan)
            plan.originals.setdefault(rel, sources[rel])
            plan.new_contents[rel] = text
            plan.edits_by_file[rel] = plan.edits_by_file.get(rel, 0) + len(removals)


def _rebuild_def(source: str, fn: ast.FunctionDef | ast.AsyncFunctionDef,
                 defmod: str, param: str, span: tuple[int, int, int, int],
                 plan: RenamePlan) -> None:
    """Rebuild the def header (single-line parameter list, verbatim segments)
    on top of the keyword-pruned text — pruning never changed line counts, so
    the header's line indices still hold."""
    sl, sc, el, ec = span
    new_sig = f"({_rebuild_params(source, fn, param)})"
    def_text = plan.new_contents.get(defmod, source)
    def_lines = def_text.splitlines(keepends=True)
    new_def = (def_lines[sl - 1][:sc] + new_sig + def_lines[el - 1][ec:])
    plan.originals.setdefault(defmod, source)
    plan.new_contents[defmod] = "".join([*def_lines[:sl - 1], new_def, *def_lines[el:]])
    plan.edits_by_file[defmod] = plan.edits_by_file.get(defmod, 0) + 1


def plan_param_drop(project_root: str | Path, func_name: str,
                    param: str) -> RenamePlan:
    """Build the project-wide drop plan for an UNUSED parameter."""
    plan = RenamePlan(old=param, new="")
    root = Path(project_root)
    files = _py_files(root)
    sources = dict(files)
    trees = _parse_trees(files)

    definition = _resolve_definition(plan, trees, func_name)
    if definition is None:
        return plan
    defmod, fn = definition
    plan.defined_in = defmod
    dotted = defmod[:-3].replace("/", ".")
    source = sources[defmod]

    if not _validate_droppable(fn, func_name, param, plan):
        return plan

    span = _pin_signature(source, fn, defmod, plan)
    if span is None:
        return plan

    pos_index = _positional_index(fn, param)

    _prune_call_sites(trees, sources, defmod, dotted, func_name, param,
                      pos_index, plan)
    _rebuild_def(source, fn, defmod, param, span, plan)

    if plan.blockers:
        plan.new_contents.clear()
        plan.originals.clear()
        plan.edits_by_file.clear()
    return plan
