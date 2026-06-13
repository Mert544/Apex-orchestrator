"""Modernize empty-collection constructors to literals.

``dict()`` → ``{}``, ``list()`` → ``[]``, ``tuple()`` → ``()``. Calling the
builtin constructor with no arguments is exactly equivalent to the literal and
marginally slower (a name lookup + call vs. a single opcode); the literal is the
idiomatic form (ruff C408). Only the ZERO-argument call is rewritten — ``dict(a=1)``,
``list(x)`` and ``tuple(it)`` carry real arguments and are left untouched. ``set()``
has no empty literal (``{}`` is a dict), so it is never rewritten.

Detection is AST-based (constructors named inside strings/comments are ignored);
the rewrite splices the exact single-line call span, so formatting survives.
Behaviour-preserving; deterministic, stdlib-only.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult

_LITERAL = {"dict": "{}", "list": "[]", "tuple": "()"}


def _targets(tree: ast.Module) -> list[ast.Call]:
    """Empty ``dict()`` / ``list()`` / ``tuple()`` calls (no args, no keywords)."""
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _LITERAL
                and not node.args and not node.keywords):
            out.append(node)
    return out


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
            continue  # multi-line call — skip to keep the splice exact
        li = node.lineno - 1
        if li >= len(lines):
            continue
        line = lines[li]
        start, end = node.col_offset, node.end_col_offset or 0
        if end <= start or end > len(line):
            continue
        assert isinstance(node.func, ast.Name)
        lines[li] = line[:start] + _LITERAL[node.func.id] + line[end:]
        changed += 1

    if changed == 0:
        return None
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(lines),
            "expected_old_content": source,
        }],
        transform_type="modernize_collection_literal",
        rationale=[
            f"Replaced {changed} empty constructor call(s) (dict()/list()/tuple()) "
            f"with literals in {rel_path} (C408, behaviour-preserving)."
        ],
    )
