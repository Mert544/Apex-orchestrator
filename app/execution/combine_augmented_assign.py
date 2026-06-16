"""Combine augmented assign — rewrite ``x = x + 1`` into ``x += 1``.

A small, surgical modernization: an assignment whose value re-applies a binary
operator to the very thing being assigned is exactly an augmented assignment::

    x = x + 1            -> x += 1
    total = total * 2    -> total *= 2
    self.n = self.n - 1  -> self.n -= 1
    d[k] = d[k] + 1      -> d[k] += 1

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the statement is an ``ast.Assign`` with EXACTLY ONE target (so
    ``a = b = a + 1`` — a multi-target assign — is left alone);
  - the target is a plain ``Name``, an attribute-chain of Names (``self.n``,
    ``a.b.c``), or a subscript of such a chain by a ``Name`` or a ``Constant``
    (``d[k]``, ``row[0]``). This keeps the target SIDE-EFFECT-FREE, so the
    single implicit read an augmented assign performs is safe; a target with a
    ``Call`` or a richer subscript index (``f().x``, ``d[g()]``, ``a[b + c]``)
    is skipped, because ``+=`` evaluates the target expression once for
    read+write and a side-effecting target would change behaviour;
  - the value is an ``ast.BinOp`` whose op is one of the augmentable operators
    (``+ - * / // % ** >> << & | ^``);
  - the BinOp's LEFT operand is STRUCTURALLY IDENTICAL to the target, compared
    by ``ast.dump``. Commutativity is NOT assumed — ``x = 1 + x`` is left alone,
    because ``+=`` places the target on the left; only ``x = x + ...`` matches;
  - the whole statement lives on a SINGLE line, so the column-span splice is
    trivially correct — multi-line assigns are skipped.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. The rewrite is rebuilt
from the ORIGINAL source text of the target and the right operand (via
``ast.get_source_segment``); if either segment can't be recovered the occurrence
is skipped. Conservative by design — the rewritten module must re-parse or the
whole plan blocks.

Rewrites are applied bottom-up and right-to-left within a line so earlier column
offsets stay valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

from app.execution._transform_base import apply_column_rewrites, is_fixture_path
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_combine_augmented_assign"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path

# The binary operators that have an augmented (``op=``) form, mapped to the
# augmented-assign symbol. ``ast.MatMult`` (``@``) is intentionally omitted —
# it is not part of the requested operator set.
_AUG_OPS: dict[type[ast.operator], str] = {
    ast.Add: "+=",
    ast.Sub: "-=",
    ast.Mult: "*=",
    ast.Div: "/=",
    ast.FloorDiv: "//=",
    ast.Mod: "%=",
    ast.Pow: "**=",
    ast.RShift: ">>=",
    ast.LShift: "<<=",
    ast.BitAnd: "&=",
    ast.BitOr: "|=",
    ast.BitXor: "^=",
}


class _Rewrite:
    """One located rewrite: replace ``line[col:end_col]`` on a single line
    (``lineno``, 1-based; cols 0-based) with ``text``."""

    __slots__ = ("lineno", "col", "end_col", "text")

    def __init__(self, lineno: int, col: int, end_col: int, text: str) -> None:
        self.lineno = lineno
        self.col = col
        self.end_col = end_col
        self.text = text


def _same_expr(a: ast.expr, b: ast.expr) -> bool:
    """True if ``a`` and ``b`` are structurally identical, ignoring expression
    context (``Load``/``Store``/``Del``).

    The assignment target carries ``ctx=Store()`` while the BinOp's left operand
    carries ``ctx=Load()``, so a raw ``ast.dump`` would never match the very
    pairs we want (``x = x + 1``). Both nodes are deep-copied and every ``ctx``
    is normalised to ``Load()`` before comparison, so only the *shape* and the
    identifiers/constants are compared. Deterministic — ``ast.dump`` of a
    normalised tree depends only on the input."""
    return ast.dump(_norm_ctx(a)) == ast.dump(_norm_ctx(b))


def _norm_ctx(node: ast.expr) -> ast.expr:
    """A deep copy of ``node`` with every expression context set to ``Load()``."""
    clone = copy.deepcopy(node)
    for sub in ast.walk(clone):
        if isinstance(getattr(sub, "ctx", None), (ast.Store, ast.Del, ast.Load)):
            sub.ctx = ast.Load()
    return clone


def _is_side_effect_free_target(node: ast.expr) -> bool:
    """True if evaluating ``node`` once (as an augmented assign's implicit read)
    is safe — it has no calls or other side-effecting sub-expressions.

    Allowed: a plain ``Name``, an attribute-chain of such (``a.b.c``), or a
    subscript of such a chain by a ``Name`` or a ``Constant`` (``d[k]``,
    ``row[0]``). Anything with a ``Call`` or a richer subscript index
    (``f().x``, ``d[g()]``, ``a[b + c]``) is rejected."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_side_effect_free_target(node.value)
    if isinstance(node, ast.Subscript):
        if not _is_side_effect_free_target(node.value):
            return False
        return isinstance(node.slice, (ast.Name, ast.Constant))
    return False


def _try_assign(stmt: ast.Assign, source: str) -> _Rewrite | None:
    """If ``stmt`` is a combinable ``target = target <op> right`` assignment,
    return its rewrite, else None."""
    # Exactly one target — never a chained ``a = b = ...`` assignment.
    if len(stmt.targets) != 1:
        return None
    value = stmt.value
    if not isinstance(value, ast.BinOp):
        return None
    symbol = _AUG_OPS.get(type(value.op))
    if symbol is None:
        return None
    # The whole statement must live on a single line — keeps the splice trivial.
    if stmt.lineno != stmt.end_lineno:
        return None

    target = stmt.targets[0]
    # The target must be a Name / attribute-chain / simple subscript so the
    # augmented assign's implicit read is side-effect-free.
    if not _is_side_effect_free_target(target):
        return None
    # The BinOp's LEFT operand must be the target itself (commutativity is not
    # assumed: ``x = 1 + x`` stays put — ``+=`` puts the target on the left).
    # Compared ignoring ctx, since the target reads Store and the operand Load.
    if not _same_expr(value.left, target):
        return None

    target_src = ast.get_source_segment(source, target)
    right_src = ast.get_source_segment(source, value.right)
    if target_src is None or right_src is None:
        return None

    replacement = f"{target_src} {symbol} {right_src}"
    return _Rewrite(stmt.lineno, stmt.col_offset, stmt.end_col_offset,
                    replacement)


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every combinable augmented-assign rewrite in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            rw = _try_assign(node, source)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up and right-to-left within a line so earlier
    column offsets stay valid."""
    return apply_column_rewrites(
        source,
        [(rw.lineno, rw.col, rw.end_col, rw.text) for rw in rewrites],
    )


def plan_combine_augmented_assign(project_root: str | Path,
                                  module_rel: str) -> RenamePlan:
    """Build the single-module combine-augmented-assign plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan rewrites every exact
    ``target = target <op> right`` assignment (single target, side-effect-free
    target, target as the BinOp's left operand) into the augmented
    ``target <op>= right``. An empty plan means nothing matched — a no-op, not a
    failure."""
    plan = RenamePlan(old=module_rel, new="combine-augmented-assign")
    if _is_fixture_path(module_rel):
        return plan

    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="combine")
