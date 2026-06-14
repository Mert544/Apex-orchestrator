"""Simplify boolean comparison — drop a redundant ``== True`` / ``is False`` …

Comparing a value against a boolean LITERAL is a readability (and sometimes
correctness) smell: the comparison merely re-derives a truth value that the
operand already carries::

    x == True   ->  x
    x == False  ->  not x
    x != True   ->  not x
    x != False  ->  x
    x is True   ->  x
    x is False  ->  not x
    x is not True   ->  not x
    x is not False  ->  x

…and the mirrored ``True == x`` / ``False is x`` etc. (the literal on either
side). The detector ``app/engine/detectors.py`` already FLAGS this shape
("compare to True/False directly (drop ``== True`` / ``== False``)") but ships no
fix; this transform closes that detect>>act gap.

PROVABLY-SAFE SUBSET — the heart of this transform.
====================================================
The rewrite is value-preserving ONLY when the non-literal operand is itself a
*genuine* ``bool``. For an arbitrary expression it is NOT, because ``==``/``is``
against a bool test value/identity, whereas the bare ``x`` / ``not x`` rewrite
tests *truthiness*:

  - ``x == True`` is ``x == 1``; ``2 == True`` is ``False`` while ``2`` is truthy,
    so ``x == True`` -> ``x`` is **unsound** for a general ``x``.
  - ``x == False`` is ``x == 0``; ``"" == False`` is ``False`` while ``not ""`` is
    ``True``, so ``x == False`` -> ``not x`` is **unsound** for a general ``x``.
  - ``x is True`` is identity with the ``True`` singleton; ``1 is True`` is
    ``False`` while ``1`` is truthy, so ``is True`` -> ``x`` is **unsound** too.

When the operand is KNOWN to be a real ``bool`` ``b`` (i.e. ``b in (True,
False)``) every one of the eight forms above is exactly equivalent:

  - ``b == True``  / ``b != False`` / ``b is True``     / ``b is not False`` == ``b``
  - ``b == False`` / ``b != True``  / ``b is False``    / ``b is not True``  == ``not b``

So this transform fires ONLY when the non-literal operand is *syntactically
guaranteed* to evaluate to a ``bool`` — no name resolution, no dataflow, no
guessing. The two AST node shapes that always yield a ``bool`` are:

  - ``ast.UnaryOp(op=ast.Not, ...)`` — Python's ``not`` operator ALWAYS returns a
    real ``True``/``False`` (it calls ``bool()`` and negates), unconditionally,
    for every object. This is the unimpeachable case.
  - ``ast.Compare`` — a comparison yields ``bool`` under standard Python value
    semantics. (A rebound ``__eq__``/``__lt__`` — e.g. NumPy arrays — can return a
    non-bool; that's the same standard-semantics assumption every comparison
    transform in this package makes, and this objective is opt-in / default-off
    like its siblings, so opting in asserts ordinary value semantics.)

Everything else is SKIPPED on purpose (correctness over coverage):

  - bare ``Name`` / ``Attribute`` / ``Subscript`` / ``Call`` / ``BoolOp`` operands
    — not provably bool (a ``Call`` could be ``isinstance(...)``, but proving the
    callee isn't shadowed needs dataflow; ``a or b`` is not a bool at all);
  - ``<`` / ``>`` / ``<=`` / ``>=`` against a bool — only the EQUALITY/IDENTITY
    operators ``==`` ``!=`` ``is`` ``is not`` are rewritten; an ordering compare
    against ``True``/``False`` is a different (and dubious) construct, left alone;
  - chained compares (``a == True == b``, ``len(ops) != 1``) — never a partial
    rewrite;
  - a compare where NEITHER side is exactly a ``True``/``False`` ``Constant`` (a
    numeric/None/str literal is not a boolean literal);
  - a compare where BOTH sides are bool literals (``True == False``) — degenerate,
    no non-literal operand to keep.

PRECEDENCE SAFETY (the H1-H7 family).
=====================================
The rewrite splices the operand's own source into the comparison's expression
context, optionally prefixed by ``not ``. ``not`` binds LOOSER than the
comparison it replaces, so a low-precedence operand must be parenthesised or the
meaning silently changes::

    a or (b < c) is False        # the compare binds tighter than `or`
        -> a or not (b < c)      # CORRECT (operand `b < c` wrapped)
        NOT  a or not b < c      # would re-associate

The non-literal operand is re-emitted through
:func:`app.execution._transform_base.splice_operand`, which keeps the operand's
ORIGINAL source segment and wraps it in parens iff precedence could otherwise
re-associate it. For the ``not x`` forms the wrapped operand is what ``not``
applies to, so ``not (a or b)`` is produced — never ``not a or b``. (In the
provably-bool subset the operand is a ``Compare`` or ``UnaryOp(Not)``; a
top-level ``Compare`` is wrapped by ``splice_operand`` since it is not atomic, so
``(a < b) is False`` -> ``not (a < b)`` correctly.)

Edits are single-line column-span replacements located by the AST (no unparse
round-trip), so comments and formatting elsewhere survive. The whole ``Compare``
must live on one line (``lineno == end_lineno``); multi-line compares are
skipped. Any operand whose source can't be recovered skips that occurrence, and
the rewritten module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left (sorted by ``(lineno,
col_offset)`` descending) so earlier offsets stay valid when several share a line
or one nests in another. Deterministic, stdlib-only (``ast``); reuses
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

__all__ = ["plan_simplify_bool_comparison"]

# The equality/identity operators we rewrite, mapped to whether the bare operand
# (False) or its negation (True) is the equivalent direct expression when the
# operand is a genuine bool ``b``. The literal value (True/False) selects which:
#
#   operator  vs True       vs False
#   ========  ============  ============
#   ==        b             not b
#   !=        not b         b
#   is        b             not b
#   is not    not b         b
#
# so the result is ``not`` iff ``(operator negates) XOR (literal is False)``.
_NEGATING_OPS: dict[type[ast.cmpop], bool] = {
    ast.Eq: False,      # ==  : same polarity as the literal
    ast.NotEq: True,    # !=  : opposite polarity
    ast.Is: False,      # is  : same polarity as the literal
    ast.IsNot: True,    # is not : opposite polarity
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


def _is_bool_literal(node: ast.expr) -> bool:
    """True iff ``node`` is EXACTLY a ``True`` / ``False`` ``Constant``.

    ``isinstance(value, bool)`` is required: ``isinstance(1, bool)`` is False, so
    a numeric ``1`` literal is correctly NOT a boolean literal. ``None`` is not a
    bool either."""
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _is_provably_bool(node: ast.expr) -> bool:
    """True iff ``node`` is SYNTACTICALLY guaranteed to evaluate to a ``bool``.

    Only two shapes qualify (see the module docstring): ``not <anything>`` (the
    ``not`` operator always returns a real bool) and a comparison (``a == b`` …),
    which yields a bool under standard value semantics. Names, attributes,
    subscripts, calls and bool-ops are NOT provably bool, so they are skipped —
    the rewrite would be unsound for a non-bool operand."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return True
    return isinstance(node, ast.Compare)


def _try_compare(node: ast.Compare, source: str) -> _Rewrite | None:
    """If ``node`` is ``b OP <bool>`` (or ``<bool> OP b``) for a single
    equality/identity operator and a provably-bool ``b``, return its direct-form
    rewrite, else None."""
    if node.lineno != node.end_lineno:  # only single-line splices
        return None
    if len(node.ops) != 1:  # chained compare — never a partial rewrite
        return None
    negates = _NEGATING_OPS.get(type(node.ops[0]))
    if negates is None:  # ordering op (< > <= >=) — never rewritten
        return None

    left, right = node.left, node.comparators[0]
    left_is_bool = _is_bool_literal(left)
    right_is_bool = _is_bool_literal(right)
    # Exactly ONE side must be a bool literal; the OTHER is the operand we keep.
    if left_is_bool == right_is_bool:
        return None  # neither side, or BOTH sides (True == False), is bool — skip
    literal = left if left_is_bool else right
    operand = right if left_is_bool else left

    if not _is_provably_bool(operand):  # unsound for a non-bool operand — skip
        return None

    src = splice_operand(source, operand)
    if src is None:  # can't recover the operand's source — skip
        return None

    # `not` iff the operator negates XOR the literal is False (see _NEGATING_OPS).
    literal_is_false = literal.value is False
    text = f"not {src}" if (negates ^ literal_is_false) else src

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset, text)


def _drop_nested(rewrites: list[_Rewrite]) -> list[_Rewrite]:
    """Drop any rewrite whose span is strictly contained in another's.

    A contained inner splice would corrupt the outer one. The OUTER rewrite
    already covers the whole expression correctly from the original source, so we
    keep it and discard any rewrite strictly inside it. Order-independent."""
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
    """Every single-operator equality/identity compare against a bool literal
    (with a provably-bool operand) in ``tree``, nested spans dropped."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            rw = _try_compare(node, source)
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


def plan_simplify_bool_comparison(
        project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module simplify-bool-comparison plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every comparison
    of a PROVABLY-BOOL operand against a ``True``/``False`` literal under an
    equality/identity operator (``==`` ``!=`` ``is`` ``is not``) to the direct
    expression (``b == True`` -> ``b``, ``b is False`` -> ``not b``, …) whose shape
    matches exactly (single operator, single line, recoverable operand). Compares
    whose operand is not provably bool are skipped (the rewrite would be unsound).
    An empty plan (no new_contents, no blockers) means nothing matched — a no-op,
    not a failure."""
    plan = RenamePlan(old=module_rel, new="simplify-bool-comparison")
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
