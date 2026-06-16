"""Fix negated membership/identity tests: ``not x in y`` -> ``x not in y``.

``not x in y`` and ``not x is y`` (E713/E714) are harder to read and easy to
misparse; the idiomatic ``x not in y`` / ``x is not y`` is exactly equivalent.
The rewrite is behaviour-preserving: each flagged ``not (Compare)`` node is
rebuilt with the negated operator and spliced back into its own source span
(single-line nodes only, so the splice stays exact).
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_and_collect_lines as _parse_and_collect_lines

_NEGATE = {ast.In: ast.NotIn, ast.Is: ast.IsNot}


def _targets(tree: ast.Module) -> list[ast.UnaryOp]:
    out: list[ast.UnaryOp] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
                and isinstance(node.operand, ast.Compare)
                and len(node.operand.ops) == 1
                and isinstance(node.operand.ops[0], (ast.In, ast.Is))):
            out.append(node)
    return out


def _corrected_source(node: ast.UnaryOp) -> str:
    cmp = node.operand
    assert isinstance(cmp, ast.Compare)
    fixed = ast.Compare(left=cmp.left, ops=[_NEGATE[type(cmp.ops[0])]()], comparators=cmp.comparators)
    return ast.unparse(fixed)


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    prepared = _parse_and_collect_lines(source, _targets)
    if prepared is None:
        return None
    nodes, lines = prepared
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
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(lines),
            "expected_old_content": source,
        }],
        transform_type="fix_negated_comparison",
        rationale=[
            f"Rewrote {changed} negated membership/identity test(s) to `not in` / "
            f"`is not` in {rel_path} (E713/E714, behaviour-preserving)."
        ],
    )
