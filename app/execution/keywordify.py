"""Convert positional call sites to keywords — the drop-enabler.

``apex signature drop`` refuses to touch a call that passes the parameter
positionally ("convert that call to keywords first"). This operation IS
that conversion: every resolvable call site of a top-level function gets
its positional arguments rewritten as ``name=value`` keywords, project-wide,
so a follow-up drop (or any signature change) has an unambiguous surface
to work on. The call's meaning is identical by construction — same values
bound to the same parameters.

Same conservative creed as the rest of the family:

  - the function must be defined exactly once at top level;
  - positional-only parameters (before ``/``) stay positional — Python
    forbids naming them;
  - a call feeding ``*args`` is left untouched (those arguments cannot be
    named, and naming the earlier ones would put positionals after
    keywords) — warned, not guessed;
  - ``f(*xs)`` starred calls block (the mapping is unknowable statically);
  - an argument whose spelling can't be verified (wrapping parens or a
    comment between arguments) blocks rather than risking ``f((x=a))``.

Insertions are intra-line (``name=`` before the argument), so comments,
formatting and line numbering survive. Reuses :class:`RenamePlan` /
:func:`apply_rename` — dry-run diffs, test verification, rollback.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _py_files
from app.execution.param_rename import _function_defs

__all__ = ["plan_keywordify"]


def _span_clean(lines: list[str], start: tuple[int, int], end: tuple[int, int],
                expect_comma: bool) -> bool:
    """True when the source between ``start`` and ``end`` (1-based line,
    0-based col) is only whitespace plus exactly one comma (when expected).
    Anything else — wrapping parens, comments — means the argument's
    spelling can't be safely prefixed with ``name=``."""
    (sl, sc), (el, ec) = start, end
    text = (lines[sl - 1][sc:ec] if sl == el
            else lines[sl - 1][sc:] + "".join(lines[sl:el - 1]) + lines[el - 1][:ec])
    stripped = text.strip()
    return stripped == ("," if expect_comma else "")


def plan_keywordify(project_root: str | Path, func_name: str) -> RenamePlan:
    """Build the project-wide positional→keyword conversion plan."""
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
    n_posonly = len(fn.args.posonlyargs)
    positional = [*fn.args.posonlyargs, *fn.args.args]
    has_vararg = fn.args.vararg is not None

    for rel, tree in trees.items():
        source = sources[rel]
        lines = source.splitlines(keepends=True)
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

        inserts: list[tuple[int, int, str]] = []  # (line, col, "name=")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            is_ours = (isinstance(f, ast.Name) and f.id in from_names) or (
                isinstance(f, ast.Attribute) and f.attr == func_name
                and ast.unparse(f.value) in module_aliases)
            if not is_ours or not node.args:
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                plan.blockers.append(
                    f"{rel}:{node.lineno}: {func_name}(*…) — the positional "
                    "mapping is unknowable statically; expand it first")
                continue
            if len(node.args) > len(positional):
                if has_vararg:
                    plan.warnings.append(
                        f"{rel}:{node.lineno}: call feeds *{fn.args.vararg.arg} — "
                        "those arguments can't be named; call left as-is")
                # No vararg = the call is already broken; not ours to touch.
                continue
            call_inserts: list[tuple[int, int, str]] = []
            clean = True
            for i, arg in enumerate(node.args):
                # The argument's left anchor: the call's "(" for the first
                # argument, the previous argument's end otherwise. Anything
                # but whitespace/one comma in between (wrapping parens, a
                # comment) makes "name=" unsafe to prefix.
                start = ((f.end_lineno, f.end_col_offset + 1) if i == 0
                         else (node.args[i - 1].end_lineno,
                               node.args[i - 1].end_col_offset))
                if not _span_clean(lines, start, (arg.lineno, arg.col_offset),
                                   expect_comma=(i > 0)):
                    plan.blockers.append(
                        f"{rel}:{node.lineno}: argument {i + 1} of {func_name}() "
                        "has non-trivial spelling (parens or a comment) — "
                        "convert that call by hand")
                    clean = False
                    break
                if i >= n_posonly:
                    call_inserts.append((arg.lineno, arg.col_offset,
                                         f"{positional[i].arg}="))
            if clean:
                inserts.extend(call_inserts)

        if plan.blockers or not inserts:
            continue
        for line_no, col, prefix in sorted(set(inserts), reverse=True):
            row = lines[line_no - 1]
            lines[line_no - 1] = row[:col] + prefix + row[col:]
        plan.originals[rel] = source
        plan.new_contents[rel] = "".join(lines)
        plan.edits_by_file[rel] = len(set(inserts))

    if plan.blockers:
        plan.new_contents.clear()
        plan.originals.clear()
        plan.edits_by_file.clear()
    return plan
