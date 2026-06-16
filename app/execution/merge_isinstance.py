"""Merge ``isinstance`` chains — collapse ``isinstance(x, A) or isinstance(x, B)``.

A small, surgical modernization: a run of ``isinstance`` checks on the SAME
target, joined by ``or``, is exactly one tuple-form ``isinstance`` call::

    isinstance(x, A) or isinstance(x, B)          -> isinstance(x, (A, B))
    isinstance(x, A) or isinstance(x, B) or ...    -> isinstance(x, (A, B, ...))
    isinstance(x, (A, B)) or isinstance(x, C)      -> isinstance(x, (A, B, C))

Apex rewrites only the exact, unambiguous shape and nothing else:

  - the whole expression is an ``ast.BoolOp(op=ast.Or)`` whose EVERY value is a
    call to a bare ``isinstance`` name with exactly two positional args, no
    keywords and no star-args;
  - the FIRST argument (the target) of every call is the SAME expression,
    compared by ``ast.dump``; any difference skips the whole BoolOp;
  - at least two ``isinstance`` calls must be present (a lone call is left
    alone); identical type texts are de-duplicated, first-seen order kept;
  - a value that is already a tuple ``(A, B)`` is flattened into the merged
    tuple;
  - the BoolOp must live on a SINGLE line so the column-span splice is trivially
    correct — multi-line BoolOps are skipped;
  - if a value is itself a BoolOp or anything non-isinstance, the whole BoolOp
    is skipped (never a partial merge), so ``isinstance(x, A) or foo()`` stands.

Edits are column-span replacements located by the AST (no unparse round-trip),
so comments and formatting elsewhere survive untouched. Conservative by design —
any source segment that can't be recovered skips that occurrence, and the
rewritten module must re-parse or the whole plan blocks.

Rewrites are applied bottom-up and right-to-left within a line so earlier
offsets stay valid. Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import apply_column_rewrites, is_fixture_path
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_merge_isinstance"]

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


def _is_isinstance_call(node: ast.AST) -> bool:
    """True for a bare ``isinstance(a, b)`` call — exactly two positional args,
    no keywords, no star-args."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and len(node.args) == 2
        and not node.keywords
        and not any(isinstance(a, ast.Starred) for a in node.args)
    )


def _type_texts(second_arg: ast.expr, source: str) -> list[str] | None:
    """Original source text(s) of an ``isinstance`` second argument. A tuple is
    flattened to its element texts; anything else is a single text. None if any
    required source segment can't be recovered."""
    if isinstance(second_arg, ast.Tuple):
        texts: list[str] = []
        for elt in second_arg.elts:
            seg = ast.get_source_segment(source, elt)
            if seg is None:
                return None
            texts.append(seg)
        return texts
    seg = ast.get_source_segment(source, second_arg)
    if seg is None:
        return None
    return [seg]


def _try_boolop(node: ast.BoolOp, source: str) -> _Rewrite | None:
    """If ``node`` is a mergeable ``isinstance`` ``or`` chain, return its
    rewrite, else None."""
    if not isinstance(node.op, ast.Or):
        return None
    if node.lineno != node.end_lineno:
        return None
    if len(node.values) < 2:
        return None
    if not all(_is_isinstance_call(v) for v in node.values):
        return None

    target_dump = ast.dump(node.values[0].args[0])
    if not all(ast.dump(v.args[0]) == target_dump for v in node.values):
        return None

    target_src = ast.get_source_segment(source, node.values[0].args[0])
    if target_src is None:
        return None

    types: list[str] = []
    for value in node.values:
        texts = _type_texts(value.args[1], source)
        if texts is None:
            return None
        for text in texts:
            if text not in types:
                types.append(text)

    replacement = f"isinstance({target_src}, ({', '.join(types)}))"
    return _Rewrite(node.lineno, node.col_offset, node.end_col_offset,
                    replacement)


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every mergeable ``isinstance`` ``or`` chain in ``tree``."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp):
            rw = _try_boolop(node, source)
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


def plan_merge_isinstance(project_root: str | Path,
                          module_rel: str) -> RenamePlan:
    """Build the single-module merge-isinstance plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan collapses every
    ``isinstance(x, A) or isinstance(x, B) ...`` chain on a shared target into a
    single tuple-form ``isinstance(x, (A, B, ...))`` call. An empty plan means
    nothing matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="merge-isinstance")
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
        reparse_phrase="merge")
