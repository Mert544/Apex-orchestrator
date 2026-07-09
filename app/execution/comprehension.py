"""Simplify accumulator loops — collapse ``out = []`` + ``for`` ``append`` into
a list comprehension.

A small, surgical modernization: a loop that does nothing but build a list by
appending one expression per iteration is just a comprehension. The transform
rewrites the EXACT shape below and nothing else::

    out = []
    for target in iterable:
        out.append(expr)

becomes a single line at the assignment's indentation::

    out = [expr for target in iterable]

Edits are line-span replacements (like bool-return): the assignment line through
the loop's last line are swapped for one comprehension line at the assignment's
own indentation, and ``expr`` / ``target`` / ``iterable`` keep their ORIGINAL
source text (via ``ast.get_source_segment``). Any of those that span more than
one line is skipped — the single-line form keeps the rewrite trivially correct.

Conservative by design — any ambiguity is a **skip**, never a guess:
  - the assignment RHS must be exactly an empty list literal ``[]``;
  - the next sibling must be a ``for`` whose body is EXACTLY one statement, an
    ``out.append(<single positional arg>)`` for the same ``out`` — no starargs,
    no keywords, no other use of ``out`` in the body;
  - the ``for`` must have no ``else``;
  - the loop target must be a plain Name or a Tuple of Names;
  - a segment that can't be recovered or that spans multiple lines skips just
    that occurrence — one bad occurrence never blocks the whole module.

The only thing that blocks the module is the final guard: if the rewritten
source won't re-parse, the whole plan blocks. Rewrites within a module are
applied bottom-up so earlier line numbers stay valid. Deterministic,
stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    AccumulatorRewrite as _Rewrite,
    accumulator_seed as _accumulator_seed,
    apply_comprehension_rewrites as _apply_comprehension_rewrites,
    is_fixture_path,
    is_name_target as _is_name_target,
    iter_statement_blocks,
    single_line_segment as _single_line_segment,
    single_name_assign_rhs as _single_name_assign_rhs,
)
from app.execution._transform_base import (
    finalize_module_rewrite as _finalize_module_rewrite,
    parse_module_source as _parse_module_source,
)
from app.execution._plan_source import read_and_parse as _read_and_parse
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_simplify_comprehension"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


def _assign_name(stmt: ast.AST) -> str | None:
    """The bound name of ``<name> = []`` (a single Name target, empty-list RHS),
    else None. ``x = [0]``, ``a, b = []``, ``x: list = []`` all yield None."""
    bound = _single_name_assign_rhs(stmt)
    if bound is None:
        return None
    name, rhs = bound
    if not isinstance(rhs, ast.List) or rhs.elts:
        return None
    return name


def _loop_body_call(for_stmt: ast.For) -> ast.Call | None:
    """The single ``Call`` of a ``for`` whose body is exactly one call-expression
    statement and whose target is a plain Name (tuple/list of Names), with no
    ``else``, else None."""
    if for_stmt.orelse or len(for_stmt.body) != 1:
        return None
    if not _is_name_target(for_stmt.target):
        return None
    stmt = for_stmt.body[0]
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return None
    return stmt.value


def _append_receiver(call: ast.Call, name: str) -> ast.Name | None:
    """The receiver ``Name`` of a ``<name>.append(...)`` call, else None."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "append":
        return None
    if not isinstance(func.value, ast.Name) or func.value.id != name:
        return None
    return func.value


def _single_positional(call: ast.Call) -> ast.expr | None:
    """The one positional (non-starred) argument of ``call``, with no keywords,
    else None."""
    if len(call.args) != 1 or call.keywords:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Starred):
        return None
    return arg


def _only_reference(node: ast.AST, name: str, receiver: ast.Name) -> bool:
    """True iff ``name`` appears within ``node`` ONLY as ``receiver`` — any other
    reference (e.g. ``out.append(out)``) keeps the loop non-trivial."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == name and sub is not receiver:
            return False
    return True


def _append_arg(for_stmt: ast.For, name: str) -> ast.expr | None:
    """The single positional argument of a ``for`` whose body is exactly one
    ``<name>.append(<arg>)`` expression statement, else None.

    Rejects: a multi-statement body, an ``else`` clause, a non-call body, a call
    that is not ``<name>.append(...)``, starargs/keywords, the wrong arg count,
    and any other reference to ``<name>`` inside the body (so the loop builds
    the list and nothing else)."""
    call = _loop_body_call(for_stmt)
    if call is None:
        return None
    receiver = _append_receiver(call, name)
    if receiver is None:
        return None
    arg = _single_positional(call)
    if arg is None:
        return None
    if not _only_reference(for_stmt.body[0], name, receiver):
        return None
    return arg


def _try_accumulator(block: list[ast.stmt], idx: int, source: str,
                     out: list[_Rewrite]) -> int:
    """If ``block[idx]`` is ``<name> = []`` followed by a matching accumulator
    ``for``, append the comprehension rewrite and return 2 (statements consumed);
    otherwise return 1. An unrecoverable / multi-line segment skips just this
    occurrence (return 1), never blocks the module."""
    seed = _accumulator_seed(block, idx, _assign_name)
    if seed is None:
        return 1
    name, nxt = seed
    stmt = block[idx]
    arg = _append_arg(nxt, name)
    if arg is None:
        return 1

    expr_src = _single_line_segment(source, arg)
    target_src = _single_line_segment(source, nxt.target)
    iter_src = _single_line_segment(source, nxt.iter)
    if expr_src is None or target_src is None or iter_src is None:
        return 1  # skip this occurrence — don't block the module

    text = f"{name} = [{expr_src} for {target_src} in {iter_src}]"
    out.append(_Rewrite(stmt.lineno, nxt.end_lineno, stmt.col_offset, text))
    return 2


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every accumulator-loop rewrite in ``tree``.

    The match needs each statement's position within its sibling block (the
    ``for`` is the assignment's next sibling), so we walk every statement list
    rather than every node."""
    rewrites: list[_Rewrite] = []
    for block in iter_statement_blocks(tree):
        i = 0
        while i < len(block):
            i += _try_accumulator(block, i, source, rewrites)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply all rewrites bottom-up so earlier line numbers stay valid,
    preserving the original last line's trailing-newline behaviour."""
    return _apply_comprehension_rewrites(source, rewrites)


def plan_simplify_comprehension(project_root: str | Path,
                                module_rel: str,
                                source: str | None = None) -> RenamePlan:
    """Build the single-module comprehension simplification plan, or its blockers.

    ``module_rel`` is a project-relative path (as produced by ``_py_files``).
    The plan rewrites every exact ``out = []`` + ``for ...: out.append(expr)``
    shape in the file into ``out = [expr for ... in ...]``; an empty plan means
    nothing matched (a no-op, not a failure).

    ``source`` lets a caller that already has the module's text in hand (Apex's
    mtime-fingerprinted source index) pass it straight in, skipping the
    project-wide disk read this otherwise does on every call. Left ``None`` the
    text is read from disk exactly as before, so every existing caller is
    unchanged. For a strict-UTF-8-clean file (the overwhelming norm) a supplied
    ``source`` is the same text this function's own read would have produced, so
    the resulting plan is identical; a file with invalid UTF-8 bytes arrives as
    the index's LENIENT (``errors="ignore"``) decode where the ``None`` path
    would have failed its strict read — any plan built from that text is then
    refused at apply time by the staleness gate's strict comparison
    (fail-closed), never silently applied."""
    plan = RenamePlan(old=module_rel, new="simplify-comprehension")
    if source is None:
        parsed = _read_and_parse(plan, project_root, module_rel)
        if parsed is None:
            return plan
        source, tree = parsed
    else:
        tree = _parse_module_source(plan, module_rel, source)
        if tree is None:
            return plan

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="simplification")
