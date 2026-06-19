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
    """Lines carrying an ``is``/``is not`` comparison against a literal.

    A line is *unsafe* — and therefore excluded — when it carries MORE than one
    ``is``/``is not`` operator. The fix is a whole-line regex that rewrites every
    ``is``/``is not`` followed by a literal-start character, so it cannot tell a
    real F632 target (``x is 5``) from a sibling identity test that merely opens
    with a bracket (``y is (z)`` / ``y is [z]``). Rewriting that sibling to
    ``==`` changes behaviour — e.g. two ``nan`` references compare ``is`` True
    but ``==`` False. With a single identity operator on the line there is no
    sibling to corrupt, so the rewrite stays provably safe.
    """
    from app.engine.detectors import _is_identity_literal

    flagged: set[int] = set()
    identity_count: dict[int, int] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Compare)
                and any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops)):
            continue
        n_ident = sum(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops)
        identity_count[node.lineno] = identity_count.get(node.lineno, 0) + n_ident
        if any(_is_identity_literal(x) for x in node.comparators):
            flagged.add(node.lineno)
    # Keep only lines whose sole identity comparison is the literal target.
    return {ln for ln in flagged if identity_count.get(ln, 0) == 1}


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
