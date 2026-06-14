"""Simplify negated comparison — rewrite ``not (a OP b)`` to its De Morgan inverse.

A negated single ordering comparison reads more directly as the inverted
operator. Python lets you negate an ordering test two equivalent ways, and the
direct form is the idiomatic one::

    not a <  b      ->  a >= b
    not a <= b      ->  a >  b
    not a >  b      ->  a <= b
    not a >= b      ->  a <  b

SCOPE — only the four ORDERING operators (``< <= > >=``):

  - the equality operators ``==`` / ``!=`` are deliberately EXCLUDED: the negated
    ``==`` / ``!=`` shape (``not (a == b)`` -> ``a != b``) is already owned by
    :mod:`app.execution.remove_double_negation`, so handling them here would
    double-register the identical rewrite. This transform inverts only the four
    ordering operators that remove_double_negation leaves alone.
  - membership / identity (``in`` / ``not in`` / ``is`` / ``is not``) belong to
    :mod:`app.execution.fix_not_in_is` and remove_double_negation — never touched
    here.

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.UnaryOp(op=ast.Not, operand=X)`` where ``X`` is an
    ``ast.Compare`` with EXACTLY ONE operator (``len(X.ops) == 1``) that is one of
    ``Lt``/``LtE``/``Gt``/``GtE`` — chained compares (``not a < b < c``,
    ``len(ops) == 2``) are left untouched because the De Morgan inverse of a
    chain is not a single inverted operator;
  - the whole ``UnaryOp`` lives on a SINGLE line (``lineno == end_lineno``) so the
    column-span splice is trivially correct — multi-line ``UnaryOp`` nodes are
    skipped;
  - both operands are re-emitted through
    :func:`app.execution._transform_base.splice_operand`, which keeps each
    operand's ORIGINAL source segment and parenthesises it iff precedence could
    otherwise change its meaning. The inverted ordering operator binds TIGHTER
    than ``or`` / ``and`` / a ternary, so a low-precedence operand MUST be
    wrapped: ``not (a or x) < b`` becomes ``(a or x) >= b`` (never the
    re-associated ``a or x >= b``). A redundant paren pair around the whole
    operand (``not (a < b)``) drops out naturally — the splice replaces the entire
    ``UnaryOp`` span.

NOTE on totality: ``not (a < b)`` equals ``a >= b`` only on a *total* order.
IEEE-754 floats break that — ``NaN`` compares false to every operator, so
``not (NaN < 1)`` is ``True`` while ``NaN >= 1`` is ``False``. The rewrite is
therefore an **opt-in** develop objective (default off, like every other
transform): opting in asserts the compared operands carry a total order, where
the inverse is exact and value-preserving (ints, strings, tuples thereof, …).

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. Conservative by design —
any source segment that can't be recovered skips that occurrence, and the
rewritten module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left (sorted by ``(lineno,
col_offset)`` descending) so earlier offsets stay valid even when two negations
share a line or one is nested in another. Deterministic, stdlib-only; reuses
:class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_column_rewrites,
    is_fixture_path,
    splice_operand,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_simplify_negated_comparison"]


# The single-operator ordering compare ops we invert, mapped to their De Morgan
# inverse text. EQUALITY ops (Eq/NotEq) are intentionally absent: their negated
# rewrite is already owned by remove_double_negation. MEMBERSHIP/IDENTITY ops
# (In/NotIn/Is/IsNot) belong to fix_not_in_is / remove_double_negation.
_INVERTED: dict[type[ast.cmpop], str] = {
    ast.Lt: " >= ",
    ast.LtE: " > ",
    ast.Gt: " <= ",
    ast.GtE: " < ",
}

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _try_unaryop(node: ast.UnaryOp, source: str) -> _Rewrite | None:
    """If ``node`` is ``not a OP b`` for a single ordering operator, return its
    De Morgan rewrite, else None."""
    if not isinstance(node.op, ast.Not):
        return None
    if node.lineno != node.end_lineno:  # only single-line splices
        return None
    compare = node.operand
    if not isinstance(compare, ast.Compare):
        return None
    if len(compare.ops) != 1:  # chained compare — never a partial rewrite
        return None
    joiner = _INVERTED.get(type(compare.ops[0]))
    if joiner is None:  # equality/membership/identity — left to its owning transform
        return None

    left = splice_operand(source, compare.left)
    right = splice_operand(source, compare.comparators[0])
    if left is None or right is None:  # can't recover source — skip
        return None

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    f"{left}{joiner}{right}")


def _drop_nested(rewrites: list[_Rewrite]) -> list[_Rewrite]:
    """Drop any rewrite whose span is strictly contained in another's.

    Nested negations could yield overlapping candidate spans; a contained inner
    splice would corrupt the outer one. The OUTER rewrite already covers the
    whole expression correctly from the original source, so we keep it and
    discard any rewrite strictly inside it. Deterministic — order-independent."""
    kept: list[_Rewrite] = []
    for rw in rewrites:
        if any(
            other is not rw
            and other.lineno == rw.lineno
            and other.col <= rw.col
            and rw.end_col <= other.end_col
            and (other.col, other.end_col) != (rw.col, rw.end_col)
            for other in rewrites
        ):
            continue  # strictly contained in another rewrite — the outer wins
        kept.append(rw)
    return kept


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every negated single-operator ordering compare in ``tree``, with
    nested/contained spans dropped so splices never overlap."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp):
            rw = _try_unaryop(node, source)
            if rw is not None:
                rewrites.append(rw)
    return _drop_nested(rewrites)


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid (handles two on a line and one nested in another)."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_simplify_negated_comparison(
        project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module simplify-negated-comparison plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every negated
    single-operator ORDERING compare to its De Morgan inverse (``not a < b`` ->
    ``a >= b``, and the ``<=`` / ``>`` / ``>=`` partners) whose shape matches
    exactly (single operator, single line, recoverable operands). Equality
    operators are excluded (remove_double_negation owns ``not a == b``). An empty
    plan (no new_contents, no blockers) means nothing matched — a no-op, not a
    failure."""
    plan = RenamePlan(old=module_rel, new="simplify-negated-comparison")
    if _is_fixture_path(module_rel):
        return plan
    path = Path(project_root) / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        plan.blockers.append(f"cannot read {module_rel}")
        return plan
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        plan.blockers.append(f"{module_rel} doesn't parse: {e}")
        return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        plan.blockers.append(
            f"{module_rel}: rewrite would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan
