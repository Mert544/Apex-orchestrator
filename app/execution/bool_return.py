"""Simplify boolean returns — collapse ``if c: return True / return False``.

A small, surgical refactor: an ``if`` whose two branches each merely return a
boolean constant is just ``return bool(c)`` (or ``return not (c)``). Apex
rewrites the EXACT shapes below and nothing else:

  - ``if c:\n    return True\nelse:\n    return False``   -> ``return bool(c)``
  - ``if c:\n    return False\nelse:\n    return True``   -> ``return not (c)``
  - the no-else form, where the opposite-constant return is the very next
    sibling statement::

        if c:
            return True
        return False                                       -> ``return bool(c)``

    (and the same with ``False`` / ``True`` swapped -> ``return not (c)``).

Edits are line-span replacements (like extract-method): the ``if`` block is
swapped for a single ``return`` line at the ``if``'s own indentation, and the
condition keeps its ORIGINAL source text (via ``ast.get_source_segment``),
wrapped in parens. Conditions that span more than one line are skipped — the
single-line form keeps the rewrite trivially correct.

Conservative by design — any ambiguity is a **blocker**, never a guess:
  - only the exact ``return True`` / ``return False`` constant shapes match;
  - a return of any non-bool-constant value is never touched;
  - the rewritten module must re-parse, or the whole plan blocks.

Rewrites within a module are applied bottom-up so earlier line numbers stay
valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_line_rewrites,
    is_fixture_path,
    iter_statement_blocks,
)
from app.execution._transform_base import (
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution._plan_source import read_and_parse as _read_and_parse
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_simplify_bool_return"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


def _bool_const(node: ast.AST) -> bool | None:
    """``True``/``False`` if ``node`` is a single ``return`` of that exact
    boolean constant, else None. ``return x``, ``return 1``, ``return None``
    and a bare ``return`` all yield None — never touched."""
    if not isinstance(node, ast.Return) or node.value is None:
        return None
    val = node.value
    if isinstance(val, ast.Constant) and val.value is True:
        return True
    if isinstance(val, ast.Constant) and val.value is False:
        return False
    return None


def _single_return_const(body: list[ast.stmt]) -> bool | None:
    """The bool constant of a body that is exactly one ``return <bool>``."""
    if len(body) != 1:
        return None
    return _bool_const(body[0])


def _replacement(then_val: bool, cond_src: str) -> str:
    """The replacement expression for ``if c -> then_val / else opposite``.
    ``True``/``False`` -> ``bool(c)``; ``False``/``True`` -> ``not (c)``."""
    if then_val:
        return f"bool({cond_src})"
    return f"not ({cond_src})"


class _Rewrite:
    """One located rewrite: replace lines [lo, hi] (1-based, inclusive) with a
    single ``return`` line at ``indent`` spaces."""

    __slots__ = ("lo", "hi", "indent", "expr")

    def __init__(self, lo: int, hi: int, indent: int, expr: str) -> None:
        self.lo = lo
        self.hi = hi
        self.indent = indent
        self.expr = expr


def _try_if(stmt: ast.stmt, block: list[ast.stmt], idx: int, source: str,
            out: list[_Rewrite]) -> int | None:
    """If ``stmt`` (at position ``idx`` in ``block``) is a simplifiable bool
    ``if``, append its rewrite and return how many statements it consumed (1
    for the if/else form, 2 for the no-else form). Returns 1 (consumed nothing
    extra) for a non-matching statement, or None on an unsafe match."""
    if not isinstance(stmt, ast.If):
        return 1
    # The test must live on a single line — keeps the source segment trivial.
    if stmt.test.lineno != stmt.test.end_lineno:
        return 1

    then_val = _single_return_const(stmt.body)
    if then_val is None:
        return 1

    if stmt.orelse:
        else_val = _single_return_const(stmt.orelse)
        if else_val is None or else_val == then_val:
            return 1
        cond_src = ast.get_source_segment(source, stmt.test)
        if cond_src is None:
            return None
        out.append(_Rewrite(stmt.lineno, stmt.end_lineno, stmt.col_offset,
                            _replacement(then_val, cond_src)))
        return 1

    # No-else form: the opposite-constant return must be the next sibling.
    nxt = block[idx + 1] if idx + 1 < len(block) else None
    nxt_val = _bool_const(nxt) if nxt is not None else None
    if nxt_val is None or nxt_val == then_val:
        return 1
    cond_src = ast.get_source_segment(source, stmt.test)
    if cond_src is None:
        return None
    out.append(_Rewrite(stmt.lineno, nxt.end_lineno, stmt.col_offset,
                        _replacement(then_val, cond_src)))
    return 2


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite] | None:
    """Every bool-return rewrite in ``tree``. None signals an unsafe condition
    (a condition whose source segment can't be recovered) so the caller blocks.

    The no-else form needs each statement's position within its sibling block,
    so we walk every statement list rather than every node."""
    rewrites: list[_Rewrite] = []
    for block in iter_statement_blocks(tree):
        i = 0
        while i < len(block):
            consumed = _try_if(block[i], block, i, source, rewrites)
            if consumed is None:
                return None
            i += consumed
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply all rewrites bottom-up so earlier line numbers stay valid.

    Each rewrite becomes a single ``return`` line at its indent, preserving the
    original last line's trailing-newline behaviour."""
    lines = source.splitlines(keepends=True)

    def _line(rw: _Rewrite) -> str:
        newline = "\n" if lines[rw.hi - 1].endswith("\n") else ""
        return " " * rw.indent + f"return {rw.expr}" + newline

    return apply_line_rewrites(
        source,
        [(rw.lo, rw.hi, [_line(rw)]) for rw in rewrites],
    )


def plan_simplify_bool_return(project_root: str | Path,
                              module_rel: str) -> RenamePlan:
    """Build the single-module bool-return simplification plan, or its blockers.

    ``module_rel`` is a project-relative path (as produced by ``_py_files``).
    The plan rewrites every exact ``if c: return True/False`` shape in the file
    into ``return bool(c)`` / ``return not (c)``; an empty plan means nothing
    matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="simplify-bool-return")
    parsed = _read_and_parse(plan, project_root, module_rel)
    if parsed is None:
        return plan
    source, tree = parsed

    rewrites = _collect_rewrites(tree, source)
    if rewrites is None:
        plan.blockers.append(
            f"{module_rel}: a bool-return condition's source couldn't be "
            "recovered — skipped to stay safe")
        return plan
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="simplification")
