"""Collapse ``x.startswith(a) or x.startswith(b)`` into ``x.startswith((a, b))``.

A small, surgical modernization: a chain of ``or``-ed ``.startswith`` (or
``.endswith``) calls on the *same* receiver is exactly the tuple form the
method already accepts. Apex rewrites only the EXACT shape below and nothing
else::

    x.startswith(a) or x.startswith(b)             -> x.startswith((a, b))
    path.name.endswith(c) or path.name.endswith(d) -> path.name.endswith((c, d))

Conservative by design — any ambiguity leaves the source untouched, never a
guess:
  - every direct value of the ``or`` must be a one-positional-arg call to the
    SAME method (all ``startswith`` or all ``endswith`` — never a mix);
  - every call's receiver must be identical (compared by ``ast.dump``);
  - a non-call, a different method, a nested boolean, keywords or starargs, or
    a non-one positional-arg count skips the whole boolean — never a partial
    merge;
  - the boolean must live on a single line (keeps the column splice trivially
    correct);
  - an argument that is already a tuple is flattened into the merged tuple;
  - identical argument texts are de-duplicated, first-seen order preserved;
  - the rewritten module must re-parse, or the whole plan blocks.

Rewrites within a module are applied bottom-up and right-to-left (sorted by
``(lineno, col_offset)`` descending) so earlier offsets stay valid.
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

__all__ = ["plan_collapse_startswith"]

_METHODS = ("startswith", "endswith")


def _matching_call(node: ast.AST, method: str) -> ast.Call | None:
    """``node`` if it is ``<recv>.<method>(<one positional arg>)`` with no
    keywords/starargs, else None."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != method:
        return None
    if node.keywords:
        return None
    if len(node.args) != 1:
        return None
    if isinstance(node.args[0], ast.Starred):
        return None
    return node


def _arg_texts(call: ast.Call, source: str) -> list[str] | None:
    """The original source text(s) the call contributes to the merged tuple.
    A tuple argument is flattened into its element texts; otherwise the single
    argument's own source. None if any required segment can't be recovered."""
    arg = call.args[0]
    if isinstance(arg, ast.Tuple):
        texts: list[str] = []
        for elt in arg.elts:
            seg = ast.get_source_segment(source, elt)
            if seg is None:
                return None
            texts.append(seg)
        return texts
    seg = ast.get_source_segment(source, arg)
    if seg is None:
        return None
    return [seg]


class _Rewrite:
    """One located rewrite: replace the single-line column span
    ``[col, end_col)`` on line ``lineno`` with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _shape_ok(node: ast.BoolOp) -> bool:
    """The boolean's pre-method shape gate: a single-line ``or`` of at least two
    values. Anything else skips the whole boolean."""
    return (
        isinstance(node.op, ast.Or)
        and len(node.values) >= 2
        and node.lineno == node.end_lineno
    )


def _common_method(values: list[ast.expr]) -> str | None:
    """The single method (all ``startswith`` or all ``endswith``) every value is
    a one-positional-arg call to, or None if no method covers them all."""
    for m in _METHODS:
        if all(_matching_call(v, m) is not None for v in values):
            return m
    return None


def _merged_arg_texts(
        calls: list[ast.Call], source: str) -> list[str] | None:
    """The de-duplicated, first-seen-order argument texts across all ``calls``,
    or None if any call's source segments can't be recovered."""
    seen: list[str] = []
    for call in calls:
        texts = _arg_texts(call, source)
        if texts is None:
            return None
        for t in texts:
            if t not in seen:
                seen.append(t)
    return seen


def _try_boolop(node: ast.BoolOp, source: str) -> _Rewrite | None:
    """The rewrite for an ``or`` of same-receiver ``startswith``/``endswith``
    calls, or None if the boolean doesn't match the exact shape."""
    if not _shape_ok(node):
        return None

    method = _common_method(node.values)
    if method is None:
        return None
    calls = [_matching_call(v, method) for v in node.values]

    # Every receiver must be identical (by ast.dump) — else skip the boolean.
    recv_dumps = {ast.dump(c.func.value) for c in calls}  # type: ignore[union-attr]
    if len(recv_dumps) != 1:
        return None

    receiver_src = splice_operand(
        source, calls[0].func.value)  # type: ignore[union-attr]
    if receiver_src is None:
        return None

    seen = _merged_arg_texts(calls, source)  # type: ignore[arg-type]
    if seen is None:
        return None

    inner = ", ".join(seen)
    text = f"{receiver_src}.{method}(({inner}))"
    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset, text)


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every collapsible boolean in ``tree``. Non-matching booleans are simply
    skipped (no blocker — they're legitimately left alone)."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp):
            rw = _try_boolop(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply all rewrites bottom-up and right-to-left so earlier column offsets
    stay valid."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_collapse_startswith(project_root: str | Path,
                             module_rel: str) -> RenamePlan:
    """Build the single-module startswith/endswith collapse plan, or blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every ``or`` of
    same-receiver ``startswith``/``endswith`` calls into the tuple form; an
    empty plan means nothing matched (a no-op, not a failure)."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="collapse-startswith",
        collect=_collect_rewrites,
        apply=_apply,
        reparse_phrase="collapse")
