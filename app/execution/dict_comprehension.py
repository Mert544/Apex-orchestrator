"""Simplify accumulator loops — collapse ``out = {}`` + ``for`` subscript-assign
into a dict comprehension.

The dict sibling of :mod:`app.execution.comprehension` (which does lists). A loop
that does nothing but build a dict by assigning one key/value per iteration is
just a comprehension. The transform rewrites the EXACT shape below and nothing
else::

    out = {}
    for target in iterable:
        out[key] = value

becomes a single line at the assignment's indentation::

    out = {key: value for target in iterable}

Edits are line-span replacements (like the list version): the assignment line
through the loop's last line are swapped for one comprehension line at the
assignment's own indentation, and ``key`` / ``value`` / ``target`` / ``iterable``
keep their ORIGINAL source text (via ``ast.get_source_segment``). Any of those
that spans more than one line is skipped — the single-line form keeps the rewrite
trivially correct.

Conservative by design — any ambiguity is a **skip**, never a guess:
  - the assignment RHS must be exactly an empty dict literal ``{}`` (an
    ``ast.Dict`` with no keys);
  - the next sibling must be a ``for`` whose body is EXACTLY one statement, an
    assignment ``out[key] = value`` for the same ``out`` (a single ``Subscript``
    target on a plain ``Name``) — no other use of ``out`` in the body;
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
    apply_line_rewrites,
    is_fixture_path,
    iter_statement_blocks,
)
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_dict_comprehension"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path


def _assign_name(stmt: ast.AST) -> str | None:
    """The bound name of ``<name> = {}`` (a single Name target, empty-dict RHS),
    else None. ``x = {1: 2}``, ``a, b = {}``, ``x: dict = {}`` all yield None.
    A set literal ``{1}`` is an ``ast.Set`` — only an empty ``ast.Dict`` matches
    (``{}`` parses as an empty dict, never a set)."""
    if not isinstance(stmt, ast.Assign):
        return None
    if len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name):
        return None
    rhs = stmt.value
    if not isinstance(rhs, ast.Dict) or rhs.keys:
        return None
    return target.id


def _is_name_target(target: ast.AST) -> bool:
    """A plain ``Name`` or a ``Tuple``/``List`` of plain Names (recursively) —
    no attribute/subscript/starred targets."""
    if isinstance(target, ast.Name):
        return True
    if isinstance(target, (ast.Tuple, ast.List)):
        return bool(target.elts) and all(_is_name_target(e) for e in target.elts)
    return False


def _subscript_kv(for_stmt: ast.For, name: str) -> tuple[ast.expr, ast.expr] | None:
    """The (key, value) of a ``for`` whose body is exactly one
    ``<name>[<key>] = <value>`` assignment, else None.

    Rejects: a multi-statement body, an ``else`` clause, a non-assignment body,
    a multi-target/chained assignment, a target that is not a ``Subscript`` on
    the plain ``Name`` ``name``, and any other reference to ``<name>`` inside the
    body (so the loop builds the dict and nothing else — e.g. ``out[k] = out``)."""
    if for_stmt.orelse:
        return None
    if len(for_stmt.body) != 1:
        return None
    if not _is_name_target(for_stmt.target):
        return None
    stmt = for_stmt.body[0]
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Subscript):
        return None
    sub_value = target.value
    if not isinstance(sub_value, ast.Name) or sub_value.id != name:
        return None
    key = target.slice
    # A slice expression (``out[a:b] = ...``) is not a dict key — skip it.
    if isinstance(key, ast.Slice):
        return None
    value = stmt.value
    # The body must touch ``name`` ONLY through this subscript receiver — any
    # other reference (in the key or the value) keeps the loop non-trivial.
    for node in ast.walk(stmt):
        if isinstance(node, ast.Name) and node.id == name and node is not sub_value:
            return None
    return key, value


class _Rewrite:
    """One located rewrite: replace lines [lo, hi] (1-based, inclusive) with a
    single comprehension line at ``indent`` spaces."""

    __slots__ = ("lo", "hi", "indent", "text")

    def __init__(self, lo: int, hi: int, indent: int, text: str) -> None:
        self.lo = lo
        self.hi = hi
        self.indent = indent
        self.text = text


def _single_line_segment(source: str, node: ast.AST) -> str | None:
    """``ast.get_source_segment`` for ``node``, but only when ``node`` lives on a
    single line — multi-line segments are rejected so the rewrite stays trivial."""
    if getattr(node, "lineno", None) != getattr(node, "end_lineno", None):
        return None
    return ast.get_source_segment(source, node)


def _try_accumulator(block: list[ast.stmt], idx: int, source: str,
                     out: list[_Rewrite]) -> int:
    """If ``block[idx]`` is ``<name> = {}`` followed by a matching accumulator
    ``for``, append the comprehension rewrite and return 2 (statements consumed);
    otherwise return 1. An unrecoverable / multi-line segment skips just this
    occurrence (return 1), never blocks the module."""
    stmt = block[idx]
    name = _assign_name(stmt)
    if name is None:
        return 1
    nxt = block[idx + 1] if idx + 1 < len(block) else None
    if not isinstance(nxt, ast.For):
        return 1
    kv = _subscript_kv(nxt, name)
    if kv is None:
        return 1
    key, value = kv

    key_src = _single_line_segment(source, key)
    value_src = _single_line_segment(source, value)
    target_src = _single_line_segment(source, nxt.target)
    iter_src = _single_line_segment(source, nxt.iter)
    if key_src is None or value_src is None or target_src is None or iter_src is None:
        return 1  # skip this occurrence — don't block the module

    text = f"{name} = {{{key_src}: {value_src} for {target_src} in {iter_src}}}"
    out.append(_Rewrite(stmt.lineno, nxt.end_lineno, stmt.col_offset, text))
    return 2


def _collect_rewrites(tree: ast.Module, source: str) -> list[_Rewrite]:
    """Every dict-accumulator-loop rewrite in ``tree``.

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
    lines = source.splitlines(keepends=True)

    def _line(rw: _Rewrite) -> str:
        newline = "\n" if lines[rw.hi - 1].endswith("\n") else ""
        return " " * rw.indent + rw.text + newline

    return apply_line_rewrites(
        source,
        [(rw.lo, rw.hi, [_line(rw)]) for rw in rewrites],
    )


def plan_dict_comprehension(project_root: str | Path,
                            module_rel: str) -> RenamePlan:
    """Build the single-module dict-comprehension simplification plan, or its
    blockers.

    ``module_rel`` is a project-relative path (as produced by ``_py_files``).
    The plan rewrites every exact ``out = {}`` + ``for ...: out[k] = v`` shape in
    the file into ``out = {k: v for ... in ...}``; an empty plan means nothing
    matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="dict-comprehension")
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
        reparse_phrase="simplification")
