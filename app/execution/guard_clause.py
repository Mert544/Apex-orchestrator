"""Guard-clause flatten with PRECEDING setup — the sibling of extract-guard-clause.

:mod:`app.execution.extract_guard_clause` already flattens the narrow shape where
a function's WHOLE body is a single else-less ``if`` (modulo a leading docstring).
This objective covers the strictly broader, still-provably-safe shape where the
function does real SETUP work first and THEN wraps the rest in one trailing
``if``::

    def f(x):                          def f(x):
        log("start")                       log("start")
        items = load(x)                    items = load(x)
        if items:              ->          if not items:
            for it in items:                   return
                handle(it)                 for it in items:
                                               handle(it)

This is behaviour-preserving for the identical reason its sibling is. The SETUP
statements run unconditionally before the ``if`` in BOTH forms and are left
byte-for-byte untouched. Originally ``if cond: body`` runs ``body`` when ``cond``
is truthy and otherwise falls off the end returning ``None``; after, the guard
``if not cond: return`` returns ``None`` when ``cond`` is falsy and otherwise runs
``body`` — identical for every input. Because the ``if`` is the LAST statement,
there is nothing after it to reorder, and the function returns no meaningful value
past the block (it falls through to an implicit ``return None``).

To keep the two objectives DISJOINT (so a module isn't flagged twice for the same
edit), this transform fires ONLY when at least one NON-docstring statement
precedes the trailing ``if`` — the pure ``if``-is-the-whole-body case is
:mod:`extract_guard_clause`'s territory and is deliberately skipped here.

Apex rewrites only this exact, unambiguous shape and nothing else:

  - a ``FunctionDef`` / ``AsyncFunctionDef`` whose LAST body statement is an
    ``ast.If``, and at least one non-docstring statement precedes it (an optional
    leading docstring does not count toward that "preceding" requirement);
  - the ``if`` has NO ``orelse`` — any ``else`` / ``elif`` changes which branch
    returns ``None``, so it is skipped;
  - the ``if`` body is non-empty;
  - the ``test`` is single-line (``lineno == end_lineno``) so its original source
    can be spliced verbatim into the inverted guard; a multi-line test is skipped;
  - the dedent unit is ``if.body[0].col_offset - if.col_offset`` spaces — the
    ``if``'s own indentation step; every non-blank if-body line must already carry
    at least that indent, or the occurrence is skipped (never an ambiguous dedent).

CONDITION INVERSION SAFETY. The guard's test is the precedence-safe negation of
the original ``test``, reusing :func:`extract_guard_clause._negated_test`: a
single-operator membership/identity compare inverts its operator (``a in b`` ->
``a not in b``), and everything else is wrapped as ``not (<original source>)`` via
the operand-splice helper. So ``if a and b:`` becomes ``if not (a and b):`` (never
``if not a and b:``), and ``if a or b:`` becomes ``if not (a or b):`` — the whole
original test is parenthesised before ``not`` is applied, so precedence can never
re-associate the meaning.

The ``if`` header line is replaced by two lines — ``if not (<test>):`` then a
``return`` indented one step under it — and the if-body lines are dedented one
level. Only the ``if`` header through its body is touched; the SETUP above it is
untouched. Edits are line-span replacements located by the AST, one per matching
function, applied bottom-up so earlier line numbers stay valid. Conservative by
design — any ambiguity is a skipped occurrence, and the rewritten module must
re-parse or the whole plan blocks. Deterministic, stdlib-only; reuses
:class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan
from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
    finalize_module_rewrite as _finalize_module_rewrite,
)
from app.execution.extract_guard_clause import (
    _FUNCTIONS,
    _Rewrite,
    _apply,
    _body_end,
    _is_docstring,
    _is_fixture_path,
    _negated_test,
)

__all__ = ["plan_guard_clause"]


def _trailing_if_with_setup(
        func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.If | None:
    """The trailing ``ast.If`` of ``func`` when REAL setup precedes it, else None.

    The function must end in an ``ast.If`` AND carry at least one non-docstring
    statement before it. A function whose whole body IS that ``if`` (modulo a
    leading docstring) is :mod:`extract_guard_clause`'s shape — returned as None
    here so the two objectives never both fire on the same function."""
    body = func.body
    if not body:
        return None
    last = body[-1]
    if not isinstance(last, ast.If):
        return None
    preceding = body[:-1]
    if preceding and _is_docstring(preceding[0]):
        preceding = preceding[1:]
    if not preceding:
        return None  # no real setup — that's extract_guard_clause's territory
    return last


def _try_func(func: ast.FunctionDef | ast.AsyncFunctionDef, source: str,
              lines: list[str]) -> _Rewrite | None:
    """If ``func`` ends in an else-less ``if`` preceded by real setup and the
    guard rewrite is unambiguous, return its rewrite, else None (skip)."""
    node = _trailing_if_with_setup(func)
    if node is None:
        return None
    if node.orelse:
        return None  # else / elif — which branch returns None differs, skip
    if not node.body:
        return None  # empty if-body — nothing to dedent (defensive)

    # Single-line test so its original source splices cleanly into the guard.
    if node.test.lineno != node.test.end_lineno:
        return None
    test_src = ast.get_source_segment(source, node.test)
    if test_src is None:
        return None

    # Dedent the if-body by exactly the ``if``'s own indentation step, so the
    # body lands at the function-body indent (where the ``if`` header sat).
    unit = node.body[0].col_offset - node.col_offset
    if unit <= 0:
        return None

    body_lo = node.body[0].lineno
    body_hi = _body_end(node.body)
    # Every non-blank if-body line must carry at least ``unit`` leading spaces,
    # or the dedent would be ambiguous (a continuation indented less than the
    # block). Skip to stay safe.
    pad = " " * unit
    for n in range(body_lo, body_hi + 1):
        line = lines[n - 1]
        if line.strip() and not line.startswith(pad):
            return None

    newline = "\n" if lines[node.lineno - 1].endswith("\n") else ""
    indent = " " * node.col_offset
    header = f"{indent}if {_negated_test(node.test, source, test_src)}:" + newline
    ret = indent + " " * unit + "return" + (newline or "\n")
    return _Rewrite(node.lineno, body_hi, header, ret, body_lo, body_hi, unit)


def _collect_rewrites(tree: ast.Module, source: str,
                      lines: list[str]) -> list[_Rewrite]:
    """Every guard-clause rewrite in ``tree``, one per matching function.

    The matched span is the trailing ``if`` through its body; a nested function
    that itself matches lives ENTIRELY inside that ``if``'s body (or in the setup
    above), so its span is disjoint from this function's — simple collection
    across all functions yields non-overlapping spans, which the bottom-up apply
    handles. (A function nested inside the matched ``if`` body would have its own
    header dedented as a body line AND, were it matched, also rewritten — an
    overlap — so we drop any candidate whose span is contained in another's.)"""
    candidates: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTIONS):
            rw = _try_func(node, source, lines)
            if rw is not None:
                candidates.append(rw)

    kept: list[_Rewrite] = []
    for rw in candidates:
        if any(
            other is not rw
            and other.lo <= rw.lo
            and rw.hi <= other.hi
            and (other.lo, other.hi) != (rw.lo, rw.hi)
            for other in candidates
        ):
            continue  # strictly contained in another match — the outer wins
        kept.append(rw)
    return kept


def plan_guard_clause(project_root: str | Path,
                      module_rel: str) -> RenamePlan:
    """Build the single-module guard-clause plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan flattens every function
    that ends in an else-less ``if`` PRECEDED by real (non-docstring) setup
    (single-line test, an unambiguous dedent) into setup + an early-return guard +
    the dedented body. Functions whose whole body is the ``if`` are left to
    extract-guard-clause. An empty plan means nothing matched — a no-op, not a
    failure."""
    plan = RenamePlan(old=module_rel, new="guard-clause")
    if _is_fixture_path(module_rel):
        return plan

    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return plan

    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return plan

    lines = source.splitlines(keepends=True)
    rewrites = _collect_rewrites(tree, source, lines)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    return _finalize_module_rewrite(
        plan, module_rel, source, new_source, len(rewrites),
        reparse_phrase="guard-clause rewrite")
