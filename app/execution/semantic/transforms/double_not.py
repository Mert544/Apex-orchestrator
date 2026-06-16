from __future__ import annotations

import ast

from ..result import SemanticPatchResult

# Inner operands we are willing to rewrite. These are all side-effect-free in
# the sense that they evaluate the same way once whether wrapped in ``bool(...)``
# or in ``not not ...``. Keeping the set narrow avoids any question about
# evaluation order or repeated side effects.
_SAFE_OPERANDS = (
    ast.Name,
    ast.Attribute,
    ast.Constant,
    ast.Compare,
)


def _is_double_not(node: ast.AST) -> bool:
    """True only for ``UnaryOp(Not, UnaryOp(Not, X))`` with a safe ``X``.

    Refuses a single ``not``, a triple ``not`` (the inner is itself a double
    not, whose operand is another ``UnaryOp`` and therefore not in the safe
    set), and ``not (not x and y)`` (the inner is a ``BoolOp``, not a plain
    ``Not``).
    """
    if not (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)):
        return False
    inner = node.operand
    if not (isinstance(inner, ast.UnaryOp) and isinstance(inner.op, ast.Not)):
        return False
    return isinstance(inner.operand, _SAFE_OPERANDS)


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    """Rewrite ``not not x`` to ``bool(x)`` for side-effect-free ``x``.

    ``not not x`` is exactly ``bool(x)`` semantically. We only rewrite the
    pattern when the operand is a plain Name/attribute/constant/compare so the
    replacement is unambiguous, and we re-parse the result before returning so
    we never hand back a corrupt file.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # A double-not that is itself the operand of an enclosing `not` is the inner
    # half of a `not not not ...` chain. The spec refuses triple (and longer)
    # nots, so collect those nodes and skip them.
    nested_under_not = {
        id(n.operand)
        for n in ast.walk(tree)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)
    }

    # Walk in source order so the chosen node is deterministic.
    for node in ast.walk(tree):
        if not _is_double_not(node):
            continue
        if id(node) in nested_under_not:
            # Inner half of a triple (or longer) `not` chain -- refuse.
            continue
        inner = node.operand  # UnaryOp(Not, X)
        operand_src = ast.get_source_segment(source, inner.operand)
        if operand_src is None:
            continue

        replacement = f"bool({operand_src})"
        new_source = _replace_span(source, node, replacement)
        if new_source is None or new_source == source:
            continue

        # Never corrupt the file: the result must still parse.
        try:
            ast.parse(new_source)
        except SyntaxError:
            continue

        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": new_source,
                "expected_old_content": source,
            }],
            transform_type="double_not_to_bool",
            rationale=[f"Replaced 'not not x' with 'bool(x)' in {rel_path}."],
        )

    return None


def _replace_span(source: str, node: ast.AST, replacement: str) -> str | None:
    """Replace the exact source span of ``node`` with ``replacement``.

    Uses the node's line/column offsets so we only touch the double-not
    expression and leave the surrounding source untouched.
    """
    end_lineno = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if node.lineno is None or node.col_offset is None or end_lineno is None or end_col is None:
        return None

    lines = source.splitlines(keepends=True)
    if node.lineno < 1 or end_lineno > len(lines):
        return None

    start_idx = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end_idx = sum(len(line) for line in lines[: end_lineno - 1]) + end_col
    if start_idx > end_idx or end_idx > len(source):
        return None

    return source[:start_idx] + replacement + source[end_idx:]
