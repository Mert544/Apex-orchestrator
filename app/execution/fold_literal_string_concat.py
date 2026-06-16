"""Fold literal string concatenation — collapse ``"a" + "b"`` into ``"ab"``.

The micro-cleanup that turns an explicit ``+`` over adjacent STRING LITERALS
into the single folded literal it always evaluates to::

    "foo" + "bar"        ->  'foobar'
    "a" + "b" + "c"      ->  'abc'

The ``+`` here is pure constant arithmetic — both sides are string literals, so
the result is fixed at parse time. Apex computes the concatenation and emits it
as one literal, removing a needless run-time operation and the visual noise of
the operator.

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the node is an ``ast.BinOp(op=ast.Add)`` whose ENTIRE left-associative ``+``
    subtree is built from ``ast.Constant`` operands that each hold a plain
    ``str`` — a chain ``"a" + "b" + "c"`` (which parses as
    ``BinOp(BinOp("a", "b"), "c")``) collapses to one literal. The fold is
    anchored at the TOPMOST eligible ``BinOp`` so the whole chain folds once;
    a contained inner ``BinOp`` is skipped (its outer node already covers it);

  - EVERY operand is a ``str`` ``Constant``. If any operand is bytes, an
    f-string (``JoinedStr``), a number, a name, a call, or any non-literal, the
    subtree is NOT eligible and is left untouched — a mixed expression like
    ``"a" + x + "b"`` never partially folds (the ``"a" + x`` part isn't two
    literals);

  - nothing inside an f-string is folded — an ``Add`` living within a
    ``JoinedStr`` / ``FormattedValue`` is skipped wholesale;

  - the folded value is emitted with :func:`repr`, which always yields a
    re-parseable, correctly quoted/escaped ``str`` literal (the original quote
    style is intentionally NOT preserved — ``repr`` guarantees validity);

  - the whole ``BinOp`` lives on a SINGLE line (``lineno == end_lineno``) so the
    column-span splice is trivially correct — multi-line concatenations are
    skipped.

Each occurrence is double-checked before it is allowed to land: the spliced
module must re-parse, and the folded literal must equal the original
concatenation when both are evaluated via :func:`ast.literal_eval` — any
mismatch or recovery failure blocks (or skips) that occurrence rather than
risk a wrong rewrite.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. Rewrites are applied
bottom-up and right-to-left (sorted by ``(lineno, col_offset)`` descending) so
earlier offsets stay valid even when two folds share a line. Deterministic,
stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import apply_column_rewrites
from app.execution._transform_base import plan_single_module_rewrite
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_fold_literal_string_concat"]


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _str_constant(node: ast.expr) -> bool:
    """True iff ``node`` is a plain ``str`` ``Constant`` (not bytes/number/etc.)."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _fold_chain(node: ast.expr) -> str | None:
    """The concatenated ``str`` for a pure string-literal ``+`` subtree, else None.

    ``node`` folds when it is either a plain ``str`` ``Constant`` or an
    ``ast.BinOp(op=ast.Add)`` whose left and right both fold. Any other shape
    (bytes, f-string, number, name, call, ``-``/``*``/...) makes the whole
    subtree ineligible, so the fold returns None and nothing changes."""
    if _str_constant(node):
        return node.value  # type: ignore[return-value]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _fold_chain(node.left)
        if left is None:
            return None
        right = _fold_chain(node.right)
        if right is None:
            return None
        return left + right
    return None


def _try_binop(node: ast.BinOp, source: str) -> _Rewrite | None:
    """If ``node`` is the topmost ``+`` over only string literals, return its fold
    rewrite, else None (the occurrence is skipped)."""
    if not isinstance(node.op, ast.Add):
        return None
    if node.lineno != node.end_lineno:  # only single-line splices
        return None

    folded = _fold_chain(node)
    if folded is None:  # mixed / non-string operand somewhere — leave it alone
        return None

    text = repr(folded)
    # Belt-and-braces: the emitted literal must itself parse back, via
    # ast.literal_eval, to EXACTLY the folded concatenation — repr() guarantees
    # this, but we re-check so a wrong literal can never land. (literal_eval is
    # used on the single emitted literal, not on the original ``a + b``
    # expression, which literal_eval rejects: it never evaluates ``+`` over
    # strings.) ``folded`` was built solely from the operand Constant values, so
    # equality here certifies the rewrite preserves the concatenation.
    try:
        if ast.literal_eval(text) != folded:
            return None
    except (ValueError, SyntaxError):
        return None

    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset, text)


def _fstring_binops(node: ast.AST) -> set[int]:
    """The ``id()`` of every ``BinOp`` living inside an f-string (``JoinedStr``).

    String folding must never touch an ``Add`` that is part of an f-string's
    formatted value — those operands are constrained differently and the splice
    columns are relative to the whole module, so we exclude them wholesale."""
    excluded: set[int] = set()
    for fstr in ast.walk(node):
        if isinstance(fstr, ast.JoinedStr):
            for inner in ast.walk(fstr):
                if isinstance(inner, ast.BinOp):
                    excluded.add(id(inner))
    return excluded


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every topmost eligible string-concat fold in ``tree``.

    Only the OUTERMOST ``BinOp`` of an eligible chain is folded: when an ``Add``
    node is itself the operand of another eligible ``Add``, its parent already
    covers it, so the inner node is skipped (no overlapping splice). Folds inside
    f-strings are excluded wholesale."""
    excluded = _fstring_binops(tree)
    # The ``id()`` of every BinOp that is the left/right of an *eligible* parent
    # BinOp — such a node is a sub-chain whose outer node already folds it.
    contained: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
                and id(node) not in excluded and _fold_chain(node) is not None):
            for child in (node.left, node.right):
                if isinstance(child, ast.BinOp):
                    contained.add(id(child))

    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.BinOp) and id(node) not in excluded
                and id(node) not in contained):
            rw = _try_binop(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier column
    offsets stay valid (handles two folds on a single line)."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_fold_literal_string_concat(
        project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module fold-literal-string-concat plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan folds every independent
    ``+`` over adjacent string literals (``"a" + "b" + "c"`` -> ``'abc'``) into
    one ``repr``-emitted literal, where the whole subtree is string constants,
    single-line, and outside any f-string. An empty plan (no new_contents, no
    blockers) means nothing matched — a no-op, not a failure."""
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="fold-literal-string-concat",
        collect=_collect_rewrites,
        apply=_apply,
        reparse_phrase="fold")
