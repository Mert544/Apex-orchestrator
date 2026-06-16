"""Simplify len comparison — rewrite ``len(x) == 0`` to ``not x`` in a boolean
context.

A collection's length-zero-ness *is* its falsiness, so in a place that only uses
the comparison as a truth value, the explicit ``len(...)`` check is noise. Apex
rewrites only the exact, unambiguous shapes — and ONLY when the comparison sits
in a boolean context, which is the safety crux::

    len(x) == 0   -> not x        # empty    <=> falsy
    len(x) != 0   -> bool(x)      # nonempty <=> truthy
    len(x) >  0   -> bool(x)      # nonempty <=> truthy
    len(x) >= 1   -> bool(x)      # nonempty <=> truthy

The match is deliberately strict — any deviation skips the occurrence:

  - the node is an ``ast.Compare`` with exactly ONE operator and ONE comparator;
  - its left is a call to a bare ``len`` *name* with exactly one positional arg
    and no keywords / no star-arg — ``len(x, y)`` or ``len(*xs)`` is left alone;
  - the comparator is an integer ``Constant`` and the (op, value) pair is one of
    the four shapes above; ``len(x) == 3`` / ``len(x) < 1`` are left alone;
  - the whole Compare lives on a SINGLE line so the column-span splice is
    trivially correct — multi-line comparisons are skipped;
  - and — the safety crux — the Compare is in a BOOLEAN CONTEXT: it IS the
    ``.test`` of an ``if`` / ``while`` / ``assert`` / conditional-expression, or
    an operand of a boolean ``and`` / ``or`` (``ast.BoolOp``), or the operand of
    a ``not`` (``ast.UnaryOp(op=Not)``). Anywhere else (e.g. ``n = len(x) == 0``,
    which must keep yielding a bool *value*) it is left untouched. When in doubt,
    skip.

Mirrored forms (``0 == len(x)``, ``0 < len(x)``) are deliberately NOT handled —
only the listed left-``len`` shapes match, so the rewrite stays unambiguous.

``x``'s ORIGINAL source is preserved verbatim via :func:`ast.get_source_segment`
(no unparse round-trip), so comments and formatting elsewhere survive untouched.
Edits are applied bottom-up and right-to-left within a line so earlier offsets
stay valid, and the rewritten module must re-parse or the whole plan blocks.

Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_column_rewrites,
    splice_operand,
)
from app.execution._transform_base import plan_single_module_rewrite
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_simplify_len_comparison"]

# The exact (operator-type, comparator-value) shapes. ``== 0`` becomes ``not x``;
# the other three become ``bool(x)`` — every one a length-zero-ness == falsiness
# identity that only holds in a boolean context.
_NOT_SHAPES = frozenset({(ast.Eq, 0)})
_BOOL_SHAPES = frozenset({
    (ast.NotEq, 0),   # len(x) != 0
    (ast.Gt, 0),      # len(x) >  0
    (ast.GtE, 1),     # len(x) >= 1
})


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _is_bare_len_call(node: ast.AST) -> bool:
    """True for a bare ``len(x)`` call — the func is a plain ``len`` Name, with
    exactly one positional arg, no keywords and no star-arg."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and not node.keywords
        and not isinstance(node.args[0], ast.Starred)
    )


def _replacement_text(node: ast.Compare, source: str) -> str | None:
    """If ``node`` is one of the four exact ``len(x) <op> <const>`` shapes,
    return its replacement (``not <x>`` or ``bool(<x>)``); else None.

    None means "not a match" — a different shape, a non-recoverable source
    segment, or a multi-line comparison — and the occurrence is skipped."""
    if node.lineno != node.end_lineno:
        return None  # single-line only, so the column splice is exact
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    if not _is_bare_len_call(node.left):
        return None

    comparator = node.comparators[0]
    if not (isinstance(comparator, ast.Constant)
            and isinstance(comparator.value, int)
            and not isinstance(comparator.value, bool)):
        return None
    key = (type(node.ops[0]), comparator.value)
    if key not in _NOT_SHAPES and key not in _BOOL_SHAPES:
        return None

    x_src = ast.get_source_segment(source, node.left.args[0])
    if x_src is None:
        return None

    if key in _NOT_SHAPES:
        # The `len(x) == 0 -> not x` shape splices x beside `not`, which binds
        # tighter than or/and/ternary — so a non-atomic x must be parenthesised
        # (`not (a or b)`, not `not a or b`).
        return f"not {splice_operand(source, node.left.args[0])}"
    return f"bool({x_src})"


def _boolean_context_compares(tree: ast.Module) -> set[int]:
    """Ids of every ``ast.Compare`` that sits in a boolean context.

    A Compare is in a boolean context when it IS the ``.test`` of an ``if`` /
    ``while`` / ``assert`` / conditional-expression, OR an operand of a boolean
    ``and`` / ``or`` (``ast.BoolOp``), OR the operand of a ``not``
    (``ast.UnaryOp(op=Not)``). Found by walking the tree and inspecting each
    boolean-using parent's relevant child slot directly — no parent map needed."""
    ids: set[int] = set()

    def _mark(child: ast.AST | None) -> None:
        if not (isinstance(child, ast.Compare)):
            return
        ids.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
            _mark(node.test)
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                _mark(value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            _mark(node.operand)
    return ids


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every boolean-context ``len(x) <op> <const>`` Compare matching one of the
    four exact shapes."""
    in_bool = _boolean_context_compares(tree)
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and id(node) in in_bool:
            text = _replacement_text(node, source)
            if text is not None:
                rewrites.append(_Rewrite(
                    node.lineno, node.col_offset, node.end_col_offset, text))
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_simplify_len_comparison(project_root: str | Path,
                                 module_rel: str) -> RenamePlan:
    """Build the single-module simplify-len-comparison plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every
    boolean-context ``len(x) == 0`` / ``!= 0`` / ``> 0`` / ``>= 1`` into
    ``not x`` / ``bool(x)``. An empty plan means nothing matched (a no-op, not a
    failure)."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="simplify-len-comparison",
        collect=_collect_rewrites,
        apply=_apply,
        reparse_phrase="simplification")
