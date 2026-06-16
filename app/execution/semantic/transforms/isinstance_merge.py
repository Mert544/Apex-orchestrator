"""Merge ored ``isinstance`` checks on one target into a single tuple call.

``isinstance(x, int) or isinstance(x, float)`` is exactly equivalent to the
clearer ``isinstance(x, (int, float))`` — but only when every ored term is an
``isinstance`` call whose *first* argument is the same, side-effect-free
expression. This transform is deliberately conservative:

* it acts only on an ``or`` (:class:`ast.BoolOp` with :class:`ast.Or`) whose
  operands are **all** ``isinstance(target, T)`` calls — a single unrelated term
  (e.g. ``isinstance(x, int) or x is None``) makes it refuse, because folding
  the isinstance terms would silently re-associate the boolean expression and
  could change precedence;
* the shared ``target`` must be a bare name or a plain attribute chain
  (``a.b.c``) — anything that could have side effects (a call, subscript, etc.)
  is refused, since collapsing the duplicated evaluations is only safe when the
  expression is pure;
* if any isinstance already passes a **tuple/list/set** of types its second
  argument is left untouched and the whole ``or`` is refused, to avoid
  producing a confusingly nested ``(A, (B, C))``;
* the merged call is re-spliced into the node's exact single-line source span,
  and the full result is re-parsed — anything that fails to parse yields
  ``None``.

The rewrite is behaviour-preserving and deterministic: the same source always
produces the same output, with no dependence on clock or randomness.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_and_collect_lines as _parse_and_collect_lines


def _is_pure_target(node: ast.expr) -> bool:
    """True for a bare name or an attribute chain rooted in a bare name.

    These evaluate with no side effects, so testing the same target twice (the
    ``or`` form) and once (the merged form) are interchangeable.
    """
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _isinstance_call(node: ast.expr) -> ast.Call | None:
    """Return ``node`` if it is a plain ``isinstance(target, T)`` call."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and not node.keywords
        and len(node.args) == 2
    ):
        return node
    return None


def _target_key(expr: ast.expr) -> str | None:
    """A canonical string for a pure target expression, else ``None``."""
    if not _is_pure_target(expr):
        return None
    return ast.unparse(expr)


def _merge_boolop(node: ast.BoolOp) -> ast.Call | None:
    """Build the merged ``isinstance(target, (...))`` for an ored node, or None.

    Refuses (returns ``None``) when any operand is not a 2-arg ``isinstance``
    call, when the first arguments differ, when the target is not side-effect
    free, or when any second argument is already a tuple/list/set.
    """
    if not isinstance(node.op, ast.Or) or len(node.values) < 2:
        return None

    target_key: str | None = None
    target_expr: ast.expr | None = None
    type_exprs: list[ast.expr] = []

    for operand in node.values:
        call = _isinstance_call(operand)
        if call is None:
            return None  # an unrelated ored term — refuse to re-associate

        key = _target_key(call.args[0])
        if key is None:
            return None  # impure / non-trivial target — refuse
        if target_key is None:
            target_key = key
            target_expr = call.args[0]
        elif key != target_key:
            return None  # different targets — refuse

        type_arg = call.args[1]
        if isinstance(type_arg, (ast.Tuple, ast.List, ast.Set)):
            return None  # already a tuple/collection form — refuse to nest
        type_exprs.append(type_arg)

    if target_expr is None or len(type_exprs) < 2:
        return None

    return ast.Call(
        func=ast.Name(id="isinstance", ctx=ast.Load()),
        args=[target_expr, ast.Tuple(elts=type_exprs, ctx=ast.Load())],
        keywords=[],
    )


def _targets(tree: ast.Module) -> list[ast.BoolOp]:
    out: list[ast.BoolOp] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and _merge_boolop(node) is not None:
            out.append(node)
    return out


def _splice_span(node: ast.BoolOp, line: str) -> tuple[int, int] | None:
    """The ``(start, end)`` column span of ``node`` in ``line``, or ``None``."""
    start, end = node.col_offset, node.end_col_offset or 0
    if end <= start or end > len(line):
        return None
    return start, end


def _rewrite_boolop_line(node: ast.BoolOp, line: str) -> str | None:
    """Return ``line`` with the ored isinstance merged, or ``None`` to skip."""
    if node.lineno != node.end_lineno:
        return None  # multi-line — skip so the splice stays exact
    merged = _merge_boolop(node)
    if merged is None:
        return None
    span = _splice_span(node, line)
    if span is None:
        return None
    start, end = span
    return line[:start] + ast.unparse(merged) + line[end:]


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    prepared = _parse_and_collect_lines(source, _targets)
    if prepared is None:
        return None
    nodes, lines = prepared
    changed = 0
    # Rightmost-first so splicing one node never shifts an earlier node's
    # columns on a shared line.
    for node in sorted(nodes, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        li = node.lineno - 1
        if li >= len(lines):
            continue
        rewritten = _rewrite_boolop_line(node, lines[li])
        if rewritten is None:
            continue
        lines[li] = rewritten
        changed += 1

    if changed == 0:
        return None

    new_content = "".join(lines)
    # Never emit something that does not parse.
    try:
        ast.parse(new_content)
    except SyntaxError:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="merge_isinstance",
        rationale=[
            f"Merged {changed} ored isinstance check(s) into a single tuple form "
            f"in {rel_path} (behaviour-preserving)."
        ],
    )
