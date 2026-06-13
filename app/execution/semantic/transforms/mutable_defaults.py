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


def _has_future_annotations(tree: ast.Module) -> bool:
    """True if the module does ``from __future__ import annotations``.

    Only then is widening an annotation to ``T | None`` safe across versions:
    annotations become strings and are never evaluated, so ``list[str] | None``
    can't raise at definition time on Python < 3.10. Without it we leave the
    annotation untouched (runtime-correct, just slightly type-checker-noisy).
    """
    for node in tree.body:
        if (isinstance(node, ast.ImportFrom) and node.module == "__future__") and (any(alias.name == "annotations" for alias in node.names)):
            return True
    return False


def _mutable_literal(node: ast.expr) -> str | None:
    """Return the safe replacement literal for a mutable default, or None."""
    for typ, rep in _LITERALS.items():
        if isinstance(node, typ):
            return rep
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)) and (node.func.id in _EMPTY_CALLS and not node.args and not node.keywords):
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
            (arg.arg, default, lit, arg)
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
    widen_annotations = _has_future_annotations(tree)

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
        for _arg, default, _lit, _node in edits:
            if default.lineno != default.end_lineno:
                ok = False  # multi-line default — skip this function, stay safe
                break
        if not ok:
            continue
        # Capture each default's *original* source text BEFORE rewriting it, so
        # the guard preserves the real value (e.g. [1, 2], not a generic []).
        guard_value = {
            id(default): lines[default.lineno - 1][default.col_offset:default.end_col_offset]
            for _arg, default, _lit, _node in mutables
        }
        # Build a flat list of in-place span replacements (default → None, and
        # optionally annotation T → "T | None"); apply right-to-left per line so
        # neighbouring spans on the same line stay valid.
        span_edits: list[tuple[int, int, int, str]] = []  # (lineno, col, end_col, text)
        for _arg, default, _lit, _node in mutables:
            span_edits.append((default.lineno, default.col_offset, default.end_col_offset, "None"))
        if widen_annotations:
            for _arg, default, _lit, arg_node in mutables:
                ann = getattr(arg_node, "annotation", None)
                if ann is None or ann.lineno != ann.end_lineno:
                    continue  # no annotation, or multi-line — stay safe
                orig = lines[ann.lineno - 1][ann.col_offset:ann.end_col_offset]
                if "None" in orig or "Optional" in orig:
                    continue  # already nullable
                span_edits.append((ann.lineno, ann.col_offset, ann.end_col_offset, f"{orig} | None"))
        for li_one, col, end_col, text in sorted(span_edits, reverse=True):
            li = li_one - 1
            line = lines[li]
            lines[li] = line[:col] + text + line[end_col:]
        # Insert guards just before the first body statement, in arg order.
        guard = "".join(
            f"{indent}if {arg} is None:\n{indent}    {arg} = {guard_value[id(default)]}\n"
            for arg, default, _lit, _node in mutables
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
