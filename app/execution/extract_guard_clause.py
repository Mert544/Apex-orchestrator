"""Extract a guard clause — flatten ``def f(): if c: body`` into an early return.

A direct reduction of nesting depth, which is exactly what drives the structural
complexity the grade penalises: a function whose ENTIRE body is a single ``if``
(no else) wraps its real work in one needless indentation level. Inverting the
condition into an early-return guard lets that work stand at the function-body
indent instead::

    def f(x):                      def f(x):
        if x > 0:          ->          if not (x > 0):
            return x * 2                   return
                                       return x * 2

This is behaviour-preserving. Originally ``if cond: body`` runs ``body`` when
``cond`` is truthy and otherwise falls off the end returning ``None``. After, the
guard ``if not (cond): return`` returns ``None`` when ``cond`` is falsy and
otherwise runs ``body`` — identical for every input. The match guarantees the
``if`` is the WHOLE body (modulo a docstring), so there is nothing after it to
reorder.

Apex rewrites only this exact, unambiguous shape and nothing else:

  - a ``FunctionDef`` / ``AsyncFunctionDef`` whose body is EXACTLY one statement,
    an ``ast.If`` — optionally preceded by a leading docstring (a single
    ``Expr`` wrapping a ``str`` constant), which is LEFT in place untouched;
  - the ``if`` has NO ``orelse`` — any ``else`` / ``elif`` changes which branch
    returns ``None``, so it is skipped;
  - the ``if`` body is non-empty (a body of only ``...``/``pass`` is still a real
    statement, so it qualifies; an *empty* body is impossible from a parse but
    guarded anyway);
  - the ``test`` is single-line (``lineno == end_lineno``) so its original source
    can be spliced verbatim into ``if not (...)``; a multi-line test is skipped;
  - the dedent unit is ``if.body[0].col_offset - if.col_offset`` spaces — the
    ``if``'s own indentation step; every non-blank if-body line must already
    carry at least that indent, or the occurrence is skipped (never a partial or
    ambiguous dedent).

The ``if`` header line is replaced by two lines — ``if not (<test>):`` then a
``return`` indented one step under it (both at the ``if``'s column) — and the
if-body lines are dedented one level so they sit at the function-body indent.
Edits are line-span replacements located by the AST, collected across every
function and applied bottom-up (highest line first) so earlier line numbers stay
valid. Conservative by design — any ambiguity is a skipped occurrence, and the
rewritten module must re-parse or the whole plan blocks. Deterministic,
stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    apply_line_rewrites,
    is_fixture_path,
)
from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_extract_guard_clause"]

# The example/test/fixture exclusion, shared across the transforms.
_is_fixture_path = is_fixture_path

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class _Rewrite:
    """One located rewrite: replace lines [lo, hi] (1-based, inclusive) — the
    ``if`` header through the end of its body — with the inverted guard header,
    a ``return`` line, then the if-body lines dedented by ``unit`` spaces.

    ``header`` / ``ret`` already carry their indentation and trailing newline;
    ``body_lo`` / ``body_hi`` (1-based, inclusive) bound the if-body lines to
    dedent."""

    __slots__ = ("lo", "hi", "header", "ret", "body_lo", "body_hi", "unit")

    def __init__(self, lo: int, hi: int, header: str, ret: str, body_lo: int,
                 body_hi: int, unit: int) -> None:
        self.lo = lo
        self.hi = hi
        self.header = header
        self.ret = ret
        self.body_lo = body_lo
        self.body_hi = body_hi
        self.unit = unit


def _body_end(body: list[ast.stmt]) -> int:
    """The last source line (1-based) spanned by a statement body."""
    return max(s.end_lineno for s in body)


def _is_docstring(stmt: ast.stmt) -> bool:
    """True for a leading docstring statement — an ``Expr`` wrapping a ``str``
    constant. Such a statement is left in place; the rest of the body is the
    single ``if`` we flatten."""
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _sole_if(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.If | None:
    """The single ``ast.If`` that is ``func``'s ENTIRE body (modulo an optional
    leading docstring), or None if the function isn't this exact shape."""
    body = func.body
    if body and _is_docstring(body[0]):
        body = body[1:]
    if len(body) != 1:
        return None
    stmt = body[0]
    return stmt if isinstance(stmt, ast.If) else None


_COMPARE_INVERT = {ast.In: "not in", ast.NotIn: "in", ast.Is: "is not", ast.IsNot: "is"}


def _negated_test(test: ast.expr, source: str, test_src: str) -> str:
    """The lint-clean negation of ``test`` for the guard. A single-operator
    membership/identity compare inverts its operator (``a in b`` -> ``a not in b``,
    ``a is b`` -> ``a is not b``) so the guard never emits ``not (a in b)`` (E713/
    E714); anything else falls back to wrapping the original text in ``not (...)``."""
    if (isinstance(test, ast.Compare) and len(test.ops) == 1
            and type(test.ops[0]) in _COMPARE_INVERT):
        left = ast.get_source_segment(source, test.left)
        right = ast.get_source_segment(source, test.comparators[0])
        if left is not None and right is not None:
            return f"{left} {_COMPARE_INVERT[type(test.ops[0])]} {right}"
    return f"not ({test_src})"


def _try_func(func: ast.FunctionDef | ast.AsyncFunctionDef, source: str,
              lines: list[str]) -> _Rewrite | None:
    """If ``func``'s whole body is a single else-less ``if`` with an unambiguous
    guard rewrite, return its rewrite, else None (the occurrence is skipped)."""
    node = _sole_if(func)
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
    """Every extract-guard-clause rewrite in ``tree``, one per matching function.

    Functions never nest within each other's matched span (the match requires the
    if to be the whole body, leaving no room for a sibling function), so simple
    collection across all functions yields non-overlapping spans."""
    rewrites: list[_Rewrite] = []
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTIONS):
            rw = _try_func(node, source, lines)
            if rw is not None:
                rewrites.append(rw)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply rewrites bottom-up (highest line first) so earlier line numbers
    stay valid. Each ``if`` header through its body becomes the inverted guard
    header, a ``return``, then the dedented body."""
    lines = source.splitlines(keepends=True)

    def _new_block(rw: _Rewrite) -> list[str]:
        body = [lines[n - 1][rw.unit:] for n in range(rw.body_lo, rw.body_hi + 1)]
        return [rw.header, rw.ret, *body]

    return apply_line_rewrites(
        source,
        [(rw.lo, rw.hi, _new_block(rw)) for rw in rewrites],
    )


def plan_extract_guard_clause(project_root: str | Path,
                              module_rel: str) -> RenamePlan:
    """Build the single-module extract-guard-clause plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan flattens every function
    whose whole body is a single else-less ``if`` (single-line test, an
    unambiguous dedent) into an early-return guard plus the dedented body. An
    empty plan means nothing matched — a no-op, not a failure."""
    plan = RenamePlan(old=module_rel, new="extract-guard-clause")
    if _is_fixture_path(module_rel):
        return plan

    root = Path(project_root)
    path = root / module_rel
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

    lines = source.splitlines(keepends=True)
    rewrites = _collect_rewrites(tree, source, lines)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        plan.blockers.append(
            f"{module_rel}: guard extraction would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan
