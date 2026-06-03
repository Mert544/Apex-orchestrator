"""Fix mutable default arguments — a classic Python footgun, fixed safely.

``def f(x=[])`` shares one list across every call, so mutations leak between
calls. The canonical fix is a sentinel default plus a guard:

    def f(x=None):
        if x is None:
            x = []

This transform applies exactly that, AST-driven and idempotent (once a default is
``None`` it is no longer flagged). It handles list/dict/set literals and the
empty ``list()``/``dict()``/``set()`` calls, rewriting one function per pass
(deepest first) so line numbers stay valid.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult

_LITERALS = {ast.List: "[]", ast.Dict: "{}", ast.Set: "set()"}
_EMPTY_CALLS = {"list": "[]", "dict": "{}", "set": "set()"}


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return _patch_mutable_defaults(rel_path, source, tree)


def _mutable_literal(node: ast.expr) -> str | None:
    """Return the safe replacement literal for a mutable default, or None."""
    for typ, rep in _LITERALS.items():
        if isinstance(node, typ):
            return rep
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in _EMPTY_CALLS and not node.args and not node.keywords:
            return _EMPTY_CALLS[node.func.id]
    return None


def _flagged_functions(tree: ast.Module) -> list[tuple[ast.AST, list[tuple[str, ast.expr, str]]]]:
    """Functions with mutable defaults → [(func, [(arg_name, default_node, literal)])]."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = node.args
        # Line up positional args with their defaults (defaults align to the tail).
        paired = list(zip(a.args[len(a.args) - len(a.defaults):], a.defaults))
        paired += [(kw, d) for kw, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
        mutables = [
            (arg.arg, default, lit)
            for arg, default in paired
            if (lit := _mutable_literal(default)) is not None
        ]
        if mutables:
            out.append((node, mutables))
    return out


def _patch_mutable_defaults(
    rel_path: str, source: str, tree: ast.Module
) -> SemanticPatchResult | None:
    flagged = _flagged_functions(tree)
    if not flagged:
        return None

    lines = source.splitlines(keepends=True)
    fixed_count = 0

    # Deepest function first so inserting guard lines never shifts a function we
    # have yet to edit.
    for func, mutables in sorted(flagged, key=lambda fm: fm[0].lineno, reverse=True):
        if not func.body:
            continue
        first_stmt = func.body[0]
        indent = " " * first_stmt.col_offset
        # Replace each mutable default span with None (right-to-left on each line).
        edits = sorted(mutables, key=lambda m: (m[1].lineno, m[1].col_offset), reverse=True)
        ok = True
        for _arg, default, _lit in edits:
            if default.lineno != default.end_lineno:
                ok = False  # multi-line default — skip this function, stay safe
                break
        if not ok:
            continue
        for _arg, default, _lit in edits:
            li = default.lineno - 1
            line = lines[li]
            lines[li] = line[:default.col_offset] + "None" + line[default.end_col_offset:]
        # Insert guards just before the first body statement, in arg order.
        guard = "".join(
            f"{indent}if {arg} is None:\n{indent}    {arg} = {lit}\n"
            for arg, _d, lit in mutables
        )
        insert_at = first_stmt.lineno - 1
        lines.insert(insert_at, guard)
        fixed_count += len(mutables)

    if fixed_count == 0:
        return None
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(lines),
            "expected_old_content": source,
        }],
        transform_type="fix_mutable_default",
        rationale=[
            f"Replaced {fixed_count} mutable default argument(s) with a None sentinel "
            f"+ guard in {rel_path} (behavior-preserving, avoids shared-state bugs)."
        ],
    )
