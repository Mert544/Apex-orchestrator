"""Collapse the three-statement temp-variable swap idiom into a tuple swap.

The classic value exchange

    tmp = a
    a = b
    b = tmp

is exactly what Python's tuple assignment expresses in one line:

    a, b = b, a

This transform rewrites that idiom **only** when it can prove the rewrite is
behaviour-preserving. The bar is deliberately high because tuple assignment
evaluates the whole right-hand side before binding any target, so a sloppy
rewrite of an idiom involving attributes / subscripts could change evaluation
order or double-evaluate a side-effecting expression.

It fires only when ALL of these hold for three *consecutive* simple ``Assign``
statements at the same block level:

* stmt1 is ``tmp = a``, stmt2 is ``a = b``, stmt3 is ``b = tmp`` — each with a
  single bare ``Name`` target and a single bare ``Name`` value (no attribute,
  subscript, tuple, starred, call, etc. on either side);
* ``a``, ``b`` and ``tmp`` are three *distinct* names (``tmp`` is neither ``a``
  nor ``b``);
* ``tmp`` is provably a throwaway: within the enclosing function it appears in
  **exactly** these three lines and nowhere else. We prove this cheaply by
  counting ``Name`` nodes for ``tmp`` in the enclosing scope — the idiom uses
  ``tmp`` precisely twice (one ``Store`` in stmt1, one ``Load`` in stmt3), so a
  total count of 2 means it is used nowhere else and the temporary can vanish.
  If we cannot establish the enclosing scope (e.g. a module-level swap, where a
  later reference could live anywhere), or the count is not exactly 2, we
  REFUSE.

It rewrites a single idiom per call (the first eligible, top-to-bottom),
preserves the indentation of stmt1, replaces the three source lines with one,
re-parses the result, and returns ``None`` on any no-op / uncertainty /
``SyntaxError`` — it never emits a patch it cannot prove re-parses.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent


def _simple_name_assign(stmt: ast.stmt) -> tuple[str, str] | None:
    """Return ``(target_name, value_name)`` for ``x = y`` with bare Names, else None.

    Refuses anything that is not a single-target ``Assign`` whose target and
    value are both plain ``ast.Name`` nodes. Attribute/subscript targets are
    rejected here precisely because tuple assignment could re-order or
    double-evaluate them.
    """
    if not isinstance(stmt, ast.Assign):
        return None
    if len(stmt.targets) != 1:
        return None
    target, value = stmt.targets[0], stmt.value
    if not isinstance(target, ast.Name) or not isinstance(value, ast.Name):
        return None
    return target.id, value.id


def _scope_of(tree: ast.Module, stmt: ast.stmt) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The innermost function enclosing ``stmt``, or ``None`` if not inside one.

    A ``None`` result means we cannot bound where ``tmp`` might be referenced
    (it could be touched anywhere later at module scope, or by a closure), so
    the caller refuses rather than guess.
    """
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or node.lineno
            if start <= stmt.lineno <= end:
                # Prefer the most deeply nested (largest start line) enclosing fn.
                if best is None or node.lineno > best.lineno:
                    best = node
    return best


def _name_count(scope: ast.AST, name: str) -> int:
    """How many ``ast.Name`` nodes in ``scope`` carry ``id == name`` (load or store)."""
    return sum(
        1 for node in ast.walk(scope)
        if isinstance(node, ast.Name) and node.id == name
    )


def _iter_blocks(tree: ast.Module):
    """Yield every statement list ("block") in the module.

    The temp-swap idiom must be three *consecutive* statements sharing a block
    level, so we examine each block's statement sequence directly rather than a
    flat ``ast.walk``.
    """
    yield tree.body
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def _find_swap(tree: ast.Module) -> tuple[ast.stmt, ast.stmt, ast.stmt] | None:
    """First eligible ``(stmt1, stmt2, stmt3)`` swap triple, top-to-bottom, else None."""
    candidates: list[tuple[int, ast.stmt, ast.stmt, ast.stmt]] = []
    for block in _iter_blocks(tree):
        for i in range(len(block) - 2):
            s1, s2, s3 = block[i], block[i + 1], block[i + 2]
            a1 = _simple_name_assign(s1)
            a2 = _simple_name_assign(s2)
            a3 = _simple_name_assign(s3)
            if a1 is None or a2 is None or a3 is None:
                continue
            tmp, a = a1            # stmt1: tmp = a
            a2t, a2v = a2          # stmt2: a = b   -> target a, value b
            b3t, b3v = a3          # stmt3: b = tmp -> target b, value tmp
            b = a2v
            # Shape: a = b uses the same `a`; b = tmp uses `b` and `tmp`.
            if a2t != a or b3t != b or b3v != tmp:
                continue
            # Three distinct names; tmp must not collide with a or b.
            if len({a, b, tmp}) != 3:
                continue
            # Prove tmp is a throwaway used only in these 3 lines of its function.
            scope = _scope_of(tree, s1)
            if scope is None:
                continue  # cannot bound tmp's reach -> refuse
            if _name_count(scope, tmp) != 2:
                continue  # tmp referenced elsewhere -> refuse
            candidates.append((s1.lineno, s1, s2, s3))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    _, s1, s2, s3 = candidates[0]
    return s1, s2, s3


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    found = _find_swap(tree)
    if found is None:
        return None
    s1, s2, s3 = found

    lines = source.splitlines(keepends=True)

    # The three statements must occupy three single, consecutive physical lines
    # (no line continuations / semicolons) so a clean 3-for-1 splice is safe.
    if (s1.end_lineno != s1.lineno
            or s2.end_lineno != s2.lineno
            or s3.end_lineno != s3.lineno):
        return None
    if not (s1.lineno + 1 == s2.lineno and s2.lineno + 1 == s3.lineno):
        return None

    i1 = s1.lineno - 1
    i3 = s3.lineno - 1
    if i3 >= len(lines):
        return None

    tmp, a = _simple_name_assign(s1)   # stmt1: tmp = a
    _, b = _simple_name_assign(s2)     # stmt2: a = b
    indent = _get_indent(lines[i1])
    # Reuse the trailing newline style of the last replaced line.
    last = lines[i3]
    newline = last[len(last.rstrip("\r\n")):] or "\n"
    replacement = f"{indent}{a}, {b} = {b}, {a}{newline}"

    new_lines = lines[:i1] + [replacement] + lines[i3 + 1:]
    new_content = "".join(new_lines)
    if new_content == source:
        return None

    # Never emit a patch we cannot prove re-parses.
    try:
        ast.parse(new_content)
    except SyntaxError:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="swap_via_tuple",
        rationale=[
            f"Collapsed a three-statement temp-variable swap into "
            f"`{a}, {b} = {b}, {a}` in {rel_path} (behaviour-preserving)."
        ],
    )
