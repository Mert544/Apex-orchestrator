"""Drop the ``f`` prefix from an f-string that has no placeholders.

``f"hello"`` is just ``"hello"`` with a misleading prefix — extremely common in
generated code (an f-string written in anticipation of an interpolation that
never arrived). The ``f`` is dead weight and a faint code smell; removing it is
behaviour-preserving.

The one subtlety is brace escaping: inside an f-string ``{{`` / ``}}`` mean a
literal ``{`` / ``}``, so dropping the prefix must un-double them. Rather than
reason about every prefix/quote/concatenation shape, the transform builds the
candidate replacement and VALIDATES it: the new literal must parse to a single
``str`` constant whose value equals the f-string's own runtime value. Any node
that fails this check is skipped untouched — so the rewrite can never change a
string, only ever remove an inert prefix.

Single-line nodes only (the splice stays exact); deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
import re

from ..result import SemanticPatchResult

_PREFIX_RE = re.compile(r"^[A-Za-z]*")


def _placeholderless_fstrings(tree: ast.Module) -> list[ast.JoinedStr]:
    """Every f-string whose parts are all plain constants (no interpolation)."""
    out: list[ast.JoinedStr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and not any(
            isinstance(v, ast.FormattedValue) for v in node.values
        ):
            out.append(node)
    return out


def _depluralized(seg: str, runtime_value: str) -> str | None:
    """The f-string source ``seg`` with its ``f`` prefix removed and braces
    un-doubled — but only if the result provably parses to ``runtime_value``.
    Returns None when no safe minimal edit exists (skip the node)."""
    prefix = _PREFIX_RE.match(seg).group(0)
    if "f" not in prefix and "F" not in prefix:
        return None  # the literal at the span start isn't the f-string (concat)
    new_prefix = prefix.replace("f", "").replace("F", "")
    body = seg[len(prefix):]
    candidate = new_prefix + body.replace("{{", "{").replace("}}", "}")
    if candidate == seg:
        return None  # nothing actually changed
    try:
        parsed = ast.parse(candidate, mode="eval").body
    except (SyntaxError, RecursionError, MemoryError):
        return None
    if (isinstance(parsed, ast.Constant) and isinstance(parsed.value, str)
            and parsed.value == runtime_value):
        return candidate
    return None


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    nodes = _placeholderless_fstrings(tree)
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
        seg = line[start:end]
        runtime_value = "".join(
            v.value for v in node.values if isinstance(v, ast.Constant)
        )
        replacement = _depluralized(seg, runtime_value)
        if replacement is None:
            continue
        lines[li] = line[:start] + replacement + line[end:]
        changed += 1

    if changed == 0:
        return None
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(lines),
            "expected_old_content": source,
        }],
        transform_type="fix_fstring_no_placeholder",
        rationale=[
            f"Removed the dead `f` prefix from {changed} placeholder-less "
            f"f-string(s) in {rel_path} (behaviour-preserving)."
        ],
    )
