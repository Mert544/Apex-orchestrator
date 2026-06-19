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
    except (SyntaxError, RecursionError, MemoryError):
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


def _has_multiline_default(mutables: list) -> bool:
    """True if any default spans multiple lines (skip the function, stay safe)."""
    return any(default.lineno != default.end_lineno for _arg, default, _lit, _node in mutables)


def _span_text(lines: list[str], node: ast.expr) -> str:
    """The exact source slice covered by a single-line ``node``."""
    return lines[node.lineno - 1][node.col_offset:node.end_col_offset]


def _annotation_edits(
    lines: list[str], mutables: list
) -> list[tuple[int, int, int, str]]:
    """Span edits widening each nullable-able annotation ``T`` to ``T | None``."""
    edits: list[tuple[int, int, int, str]] = []
    for _arg, _default, _lit, arg_node in mutables:
        ann = getattr(arg_node, "annotation", None)
        if ann is None or ann.lineno != ann.end_lineno:
            continue  # no annotation, or multi-line — stay safe
        orig = _span_text(lines, ann)
        if "None" in orig or "Optional" in orig:
            continue  # already nullable
        edits.append((ann.lineno, ann.col_offset, ann.end_col_offset, f"{orig} | None"))
    return edits


def _collect_span_edits(
    lines: list[str], mutables: list, widen_annotations: bool
) -> list[tuple[int, int, int, str]]:
    """All in-place span replacements: each default → None, optional annotation widening."""
    # Apply right-to-left per line so neighbouring spans on the same line stay valid.
    edits: list[tuple[int, int, int, str]] = [
        (default.lineno, default.col_offset, default.end_col_offset, "None")
        for _arg, default, _lit, _node in mutables
    ]
    if widen_annotations:
        edits += _annotation_edits(lines, mutables)
    return edits


def _apply_span_edits(lines: list[str], span_edits: list[tuple[int, int, int, str]]) -> None:
    """Splice each ``(lineno, col, end_col, text)`` in place, right-to-left."""
    for li_one, col, end_col, text in sorted(span_edits, reverse=True):
        li = li_one - 1
        line = lines[li]
        lines[li] = line[:col] + text + line[end_col:]


def _build_guard(indent: str, mutables: list, guard_value: dict) -> str:
    """The ``if arg is None: arg = <value>`` guard block, in arg order."""
    return "".join(
        f"{indent}if {arg} is None:\n{indent}    {arg} = {guard_value[id(default)]}\n"
        for arg, default, _lit, _node in mutables
    )


def _is_docstring(stmt: ast.AST) -> bool:
    """True if ``stmt`` is a leading docstring (``ast.Expr`` of a ``str`` constant)."""
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _guard_insert_index(func: ast.AST) -> int:
    """0-based line index at which to splice the guard block.

    If the function leads with a docstring, the guard goes *after* it so the
    docstring stays ``body[0]`` (preserving ``func.__doc__``); otherwise it goes
    above the first statement as before.
    """
    first_stmt = func.body[0]
    if _is_docstring(first_stmt):
        return first_stmt.end_lineno  # 0-based line right after the docstring
    return first_stmt.lineno - 1


def _patch_one_function(lines: list[str], func: ast.AST, mutables: list, widen_annotations: bool) -> int:
    """Rewrite one function in ``lines``; return the count of defaults fixed."""
    if not func.body:
        return 0
    if _has_multiline_default(mutables):
        return 0
    first_stmt = func.body[0]
    indent = " " * first_stmt.col_offset
    insert_index = _guard_insert_index(func)
    # Capture each default's *original* source text BEFORE rewriting it, so
    # the guard preserves the real value (e.g. [1, 2], not a generic []).
    guard_value = {
        id(default): _span_text(lines, default)
        for _arg, default, _lit, _node in mutables
    }
    _apply_span_edits(lines, _collect_span_edits(lines, mutables, widen_annotations))
    # Insert guards at the first non-docstring body line, in arg order, so a
    # leading docstring stays the function's docstring.
    lines.insert(insert_index, _build_guard(indent, mutables, guard_value))
    return len(mutables)


def _docstringed_functions(tree: ast.AST) -> int:
    """Count functions that lead with a docstring (for a preservation check)."""
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and _is_docstring(node.body[0])
    )


def _validates(new_content: str, original_tree: ast.Module) -> bool:
    """Re-parse the rewrite and confirm no docstring was demoted.

    The mutable-default fix must be behaviour-preserving: any function that had a
    docstring before must still expose it as ``body[0]`` afterwards. We compare
    the docstringed-function count before and after; a regression (guard wedged
    above a docstring) lowers the count and fails the check.
    """
    try:
        new_tree = ast.parse(new_content)
    except (SyntaxError, RecursionError, MemoryError):
        return False
    return _docstringed_functions(new_tree) >= _docstringed_functions(original_tree)


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
        fixed_count += _patch_one_function(lines, func, mutables, widen_annotations)

    if fixed_count == 0:
        return None

    new_content = "".join(lines)
    if not _validates(new_content, tree):
        return None  # self-check failed — refuse rather than emit a bad patch

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="fix_mutable_default",
        rationale=[
            f"Replaced {fixed_count} mutable default argument(s) with a None sentinel "
            f"+ guard in {rel_path} (behavior-preserving, avoids shared-state bugs)."
        ],
    )
