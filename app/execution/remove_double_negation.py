"""Remove double negation — simplify negated comparisons and double negations.

The readability cleanup that turns an awkward negation into its direct,
equivalent form. Python lets you write a negated equality/identity/membership
test the long way round, and a doubled ``not`` is always redundant::

    not (a == b)        ->  a != b
    not (a != b)        ->  a == b
    not (a is b)        ->  a is not b
    not (a is not b)    ->  a is b
    not (a in b)        ->  a not in b
    not (a not in b)    ->  a in b
    not not x           ->  bool(x)

Apex rewrites only the exact, unambiguous shapes and nothing else:

  - the node is an ``ast.UnaryOp(op=ast.Not, operand=X)`` where either

      * ``X`` is an ``ast.Compare`` with EXACTLY ONE operator
        (``len(X.ops) == 1``) that is ``Eq``/``NotEq``/``Is``/``IsNot``/``In``/
        ``NotIn`` — the operator is INVERTED to its partner and the compare's
        original left and comparator source segments are kept verbatim. Chained
        compares (``not a == b == c``) and ORDERING operators (``not a < b``)
        are left untouched: ``not (a < b)`` is ``a >= b`` only on a total order,
        and floats/NaN make that rewrite unsafe; or

      * ``X`` is itself an ``ast.UnaryOp(op=ast.Not, operand=Y)`` — the double
        negation collapses to ``bool(<Y source>)`` (``not not x`` -> ``bool(x)``,
        ``bool(...)`` so the value is normalised exactly as the two ``not``\\ s
        did);

  - the whole ``UnaryOp`` lives on a SINGLE line (``lineno == end_lineno``) so
    the column-span splice is trivially correct — multi-line ``UnaryOp`` nodes
    are skipped;

  - the replacement is rebuilt from the ORIGINAL source segments of the inner
    operands (so attribute/subscript/call operands and any inner formatting
    survive). A redundant paren pair around the operand (``not (a == b)``) is
    dropped as a natural consequence — the splice replaces the entire
    ``UnaryOp`` span.

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

__all__ = ["plan_remove_double_negation"]


# The single-operator compare ops we invert, mapped to their negated-form text.
# ORDERING ops (Lt/LtE/Gt/GtE) are intentionally absent: their inverse only
# holds on a total order, and floats/NaN make it unsafe to rewrite.
_INVERTED: dict[type[ast.cmpop], str] = {
    ast.Eq: " != ",
    ast.NotEq: " == ",
    ast.Is: " is not ",
    ast.IsNot: " is ",
    ast.In: " not in ",
    ast.NotIn: " in ",
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
    """If ``node`` is a negated single-operator inequality/identity/membership
    compare, or a double ``not``, return its rewrite, else None."""
    if not isinstance(node.op, ast.Not):
        return None
    if node.lineno != node.end_lineno:  # only single-line splices
        return None

    operand = node.operand

    # Double negation: not not x -> bool(x)
    if isinstance(operand, ast.UnaryOp) and isinstance(operand.op, ast.Not):
        inner = ast.get_source_segment(source, operand.operand)
        if inner is None:  # can't recover source — skip
            return None
        return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                        f"bool({inner})")

    # Negated single-operator compare: not (a == b) -> a != b, etc.
    if not isinstance(operand, ast.Compare):
        return None
    if len(operand.ops) != 1:  # chained compare — never a partial rewrite
        return None
    joiner = _INVERTED.get(type(operand.ops[0]))
    if joiner is None:  # ordering op or unhandled — leave it alone
        return None

    left = splice_operand(source, operand.left)
    right = splice_operand(source, operand.comparators[0])
    if left is None or right is None:  # can't recover source — skip
        return None

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    f"{left}{joiner}{right}")


def _drop_nested(rewrites: list[_Rewrite]) -> list[_Rewrite]:
    """Drop any rewrite whose span is contained in another's.

    Nested negations (``not not not x``) yield overlapping candidate spans; a
    contained inner splice would corrupt the outer one. The OUTER rewrite already
    covers the whole expression correctly from the original source, so we keep it
    and discard any rewrite strictly inside it. Deterministic — order-independent."""
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
    """Every negated single-operator compare and double negation in ``tree``,
    with nested/contained spans dropped so splices never overlap."""
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


def plan_remove_double_negation(
        project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module remove-double-negation plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every negated
    single-operator equality/identity/membership compare to its inverted form
    (``not (a == b)`` -> ``a != b``) and every double negation to a ``bool(...)``
    call (``not not x`` -> ``bool(x)``) whose shape matches exactly (single
    operator, single line, recoverable operands). An empty plan (no
    new_contents, no blockers) means nothing matched — a no-op, not a failure."""
    plan = RenamePlan(old=module_rel, new="remove-double-negation")
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
