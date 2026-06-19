"""Fix identity comparisons against a literal: ``x is 5`` -> ``x == 5``.

Comparing with ``is``/``is not`` to an int/str/bytes/tuple/... literal only
works by accident of CPython interning (Python itself warns, F632); equality is
what was meant. The rewrite is behaviour-correcting and applied only on the
exact lines the AST flagged, and only when the ``is`` is followed by a literal
(so ``is None`` / ``is True`` / ``is other_var`` are never touched).
"""

from __future__ import annotations

import ast
import re

from ..result import SemanticPatchResult

# `is not` / `is` immediately followed by a literal start (digit, quote, or an
# opening bracket of a list/dict/set/tuple literal). `is None`/`is True`/`is x`
# start with a letter and so never match.
_IS_NOT_LIT = re.compile(r"\bis\s+not\s+(?=[\"'\d(\[{])")
_IS_LIT = re.compile(r"\bis\s+(?=[\"'\d(\[{])")


def _fix_line(line: str) -> str:
    line = _IS_NOT_LIT.sub("!= ", line)
    line = _IS_LIT.sub("== ", line)
    return line


def _flagged_lines(tree: ast.Module) -> set[int]:
    from app.engine.detectors import _is_identity_literal

    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops
        ) and any(_is_identity_literal(x) for x in node.comparators):
            lines.add(node.lineno)
    return lines


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    flagged = _flagged_lines(tree)
    if not flagged:
        return None

    src_lines = source.splitlines(keepends=True)
    new_lines = list(src_lines)
    changed = 0
    for lineno in sorted(flagged):
        if lineno > len(src_lines):
            continue
        fixed = _fix_line(src_lines[lineno - 1])
        if fixed != src_lines[lineno - 1]:
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
        transform_type="fix_identity_literal",
        rationale=[
            f"Replaced {changed} identity-vs-literal comparison(s) (`is`/`is not`) with "
            f"`==`/`!=` in {rel_path} (behaviour-correcting; F632)."
        ],
    )
