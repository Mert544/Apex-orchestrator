"""Simplify ``None`` comparisons: ``x == None`` -> ``x is None`` (and ``!=``).

``== None`` / ``!= None`` are flagged by PEP 8 (E711): ``None`` is a singleton,
so identity (``is`` / ``is not``) is both more correct and idiomatic. The
rewrite is unconditionally behaviour-preserving for ``None`` because ``None``
compares equal *only* to itself; rebuilding the flagged ``Compare`` node with
``Is`` / ``IsNot`` and splicing it back into its own single-line source span
keeps the rest of the line byte-for-byte identical.

Scope (deliberately conservative):

* ``x == None`` / ``None == x``  -> ``x is None``
* ``x != None`` / ``None != x``  -> ``x is not None``

REFUSED on purpose: ``== True`` / ``== False`` / ``!= True``. Those are *not*
semantics-preserving when the operand is non-bool. ``if x == True:`` is true
only when ``x`` is exactly ``True`` (or ``1``), whereas ``if x:`` is true for
any truthy value (``2``, ``"s"``, ``[0]``, ...), and ``if not x:`` differs
symmetrically. Since this transform cannot prove the operand is a ``bool``, it
leaves every boolean comparison untouched rather than silently change runtime
behaviour. Only the always-safe ``None`` rewrites are emitted.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult

# Eq/NotEq against a `None` literal -> the matching identity operator.
_IDENTITY = {ast.Eq: ast.Is, ast.NotEq: ast.IsNot}


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _targets(tree: ast.Module) -> list[ast.Compare]:
    """Single-op ``==``/``!=`` comparisons with exactly one ``None`` side."""
    out: list[ast.Compare] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if len(node.ops) != 1 or len(node.comparators) != 1:
            continue
        if not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            continue
        left_none = _is_none(node.left)
        right_none = _is_none(node.comparators[0])
        # Exactly one operand is `None` (skip the degenerate `None == None`,
        # where the rewrite is pointless and the "simple operand" is absent).
        if left_none == right_none:
            continue
        out.append(node)
    return out


def _corrected_source(node: ast.Compare) -> str:
    op = _IDENTITY[type(node.ops[0])]()
    # Normalise so the non-``None`` operand leads: ``None == x`` -> ``x is None``.
    if _is_none(node.left):
        left, comparator = node.comparators[0], node.left
    else:
        left, comparator = node.left, node.comparators[0]
    fixed = ast.Compare(left=left, ops=[op], comparators=[comparator])
    return ast.unparse(fixed)


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    nodes = _targets(tree)
    if not nodes:
        return None

    lines = source.splitlines(keepends=True)
    changed = 0
    # Rightmost-first so splicing one node never shifts an earlier node's columns.
    for node in sorted(nodes, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        if node.lineno != node.end_lineno:
            continue  # multi-line — skip to keep the splice exact
        li = node.lineno - 1
        if li >= len(lines):
            continue
        line = lines[li]
        start, end = node.col_offset, node.end_col_offset or 0
        if end <= start or end > len(line):
            continue
        lines[li] = line[:start] + _corrected_source(node) + line[end:]
        changed += 1

    if changed == 0:
        return None

    new_content = "".join(lines)
    # Never emit something that doesn't parse, and treat a no-op as no result.
    if new_content == source:
        return None
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
        transform_type="simplify_comparison",
        rationale=[
            f"Rewrote {changed} `None` comparison(s) to `is` / `is not` in "
            f"{rel_path} (E711, behaviour-preserving)."
        ],
    )
