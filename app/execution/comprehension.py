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

from app.execution.cross_file_rename import RenamePlan

__all__ = ["plan_simplify_comprehension"]


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded (its repetition is often deliberate
    boilerplate). A local copy — importing this from health_score created a
    health_score <-> dedup import cycle, and the grade now reads dedup."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _assign_name(stmt: ast.AST) -> str | None:
    """The bound name of ``<name> = []`` (a single Name target, empty-list RHS),
    else None. ``x = [0]``, ``a, b = []``, ``x: list = []`` all yield None."""
    if not isinstance(stmt, ast.Assign):
        return None
    if len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name):
        return None
    rhs = stmt.value
    if not isinstance(rhs, ast.List) or rhs.elts:
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


def _append_arg(for_stmt: ast.For, name: str) -> ast.expr | None:
    """The single positional argument of a ``for`` whose body is exactly one
    ``<name>.append(<arg>)`` expression statement, else None.

    Rejects: a multi-statement body, an ``else`` clause, a non-call body, a call
    that is not ``<name>.append(...)``, starargs/keywords, the wrong arg count,
    and any other reference to ``<name>`` inside the body (so the loop builds
    the list and nothing else)."""
    if for_stmt.orelse:
        return None
    if len(for_stmt.body) != 1:
        return None
    if not _is_name_target(for_stmt.target):
        return None
    stmt = for_stmt.body[0]
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return None
    call = stmt.value
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "append":
        return None
    if not isinstance(func.value, ast.Name) or func.value.id != name:
        return None
    if len(call.args) != 1 or call.keywords:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Starred):
        return None
    # The body must touch ``name`` ONLY through this ``.append`` receiver —
    # any other reference (e.g. ``out.append(out)``) keeps the loop non-trivial.
    receiver = func.value
    for node in ast.walk(stmt):
        if isinstance(node, ast.Name) and node.id == name and node is not receiver:
            return None
    return arg


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


def _statement_blocks(tree: ast.Module):
    """Yield every list-of-statements in the tree (module body, function/class
    bodies, if/for/while/with/try blocks). Order doesn't matter — rewrites are
    sorted before they're applied."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and all(
                    isinstance(s, ast.stmt) for s in block):
                yield block
        handlers = getattr(node, "handlers", None)
        if isinstance(handlers, list):
            for handler in handlers:
                if isinstance(handler, ast.ExceptHandler) and handler.body:
                    yield handler.body


def _try_accumulator(block: list[ast.stmt], idx: int, source: str,
                     out: list[_Rewrite]) -> int:
    """If ``block[idx]`` is ``<name> = []`` followed by a matching accumulator
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
    for block in _statement_blocks(tree):
        i = 0
        while i < len(block):
            i += _try_accumulator(block, i, source, rewrites)
    return rewrites


def _apply(source: str, rewrites: list[_Rewrite]) -> str:
    """Apply all rewrites bottom-up so earlier line numbers stay valid."""
    lines = source.splitlines(keepends=True)
    for rw in sorted(rewrites, key=lambda r: r.lo, reverse=True):
        last = lines[rw.hi - 1]
        newline = "\n" if last.endswith("\n") else ""
        new_line = " " * rw.indent + rw.text + newline
        lines[rw.lo - 1:rw.hi] = [new_line]
    return "".join(lines)


def plan_simplify_comprehension(project_root: str | Path,
                                module_rel: str) -> RenamePlan:
    """Build the single-module comprehension simplification plan, or its blockers.

    ``module_rel`` is a project-relative path (as produced by ``_py_files``).
    The plan rewrites every exact ``out = []`` + ``for ...: out.append(expr)``
    shape in the file into ``out = [expr for ... in ...]``; an empty plan means
    nothing matched (a no-op, not a failure)."""
    plan = RenamePlan(old=module_rel, new="simplify-comprehension")
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

    rewrites = _collect_rewrites(tree, source)
    if not rewrites:
        return plan  # nothing to do — empty plan (ok is False, no blockers)

    new_source = _apply(source, rewrites)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        plan.blockers.append(
            f"{module_rel}: simplification would not re-parse ({e}) — blocked")
        return plan
    if new_source == source:
        return plan

    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = len(rewrites)
    return plan
