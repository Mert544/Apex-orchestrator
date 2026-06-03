"""Behavior-preserving code modernization transforms.

Unlike the security transforms (which fix risky patterns), these tidy code into
its idiomatic form without changing behavior. Currently:

  • ``x == None`` → ``x is None`` and ``x != None`` → ``x is not None``.
    ``None`` is a singleton, so identity is the correct, PEP 8-mandated test;
    it is strictly equivalent for ``None`` and actually *more* correct when a
    type overrides ``__eq__``.

Detection is AST-based (so comparisons inside strings/comments are ignored); the
rewrite is applied only on the exact lines the AST flagged.
"""

from __future__ import annotations

import ast
import re

from ..result import SemanticPatchResult

_EQ_NONE = re.compile(r"==\s*None")
_NE_NONE = re.compile(r"!=\s*None")
_NONE_EQ = re.compile(r"None\s*==")
_NONE_NE = re.compile(r"None\s*!=")


def _modernize_line(line: str) -> str:
    line = _NE_NONE.sub("is not None", line)
    line = _EQ_NONE.sub("is None", line)
    line = _NONE_NE.sub("None is not", line)
    line = _NONE_EQ.sub("None is", line)
    return line


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return _patch_none_comparison(rel_path, source, tree)


def _none_comparison_lines(tree: ast.Module) -> set[int]:
    """Line numbers of real ``== None`` / ``!= None`` comparisons."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            if isinstance(comparator, ast.Constant) and comparator.value is None:
                lines.add(comparator.lineno)
            # also catch `None == x`
        if isinstance(node.left, ast.Constant) and node.left.value is None:
            lines.add(node.left.lineno)
    return lines


def _patch_none_comparison(
    rel_path: str, source: str, tree: ast.Module
) -> SemanticPatchResult | None:
    flagged = _none_comparison_lines(tree)
    if not flagged:
        return None

    src_lines = source.splitlines(keepends=True)
    changed = 0
    new_lines = list(src_lines)
    for lineno in sorted(flagged):
        if lineno > len(src_lines):
            continue
        line = src_lines[lineno - 1]
        fixed = _modernize_line(line)
        if fixed != line:
            new_lines[lineno - 1] = fixed
            changed += 1

    if changed == 0:
        return None
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(new_lines),
            "expected_old_content": source,
        }],
        transform_type="modernize_none_comparison",
        rationale=[
            f"Replaced {changed} `== None`/`!= None` comparison(s) with "
            f"`is None`/`is not None` in {rel_path} (PEP 8, behavior-preserving)."
        ],
    )
