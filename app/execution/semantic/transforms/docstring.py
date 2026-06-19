from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent

_DEF = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _doc_text(node: ast.AST, title: str, multiple: bool) -> str:
    """A one-line docstring body for ``node``.

    With a single undocumented symbol we honour the caller's ``title`` (the
    established convention). With *several* symbols in one pass we derive each
    body from the symbol's own name instead, so the file does not gain N copies
    of one identical module-level boilerplate — every inserted docstring stays
    distinct and traceable to its symbol.
    """
    if multiple:
        name = getattr(node, "name", "") or title.strip(".")
        return name.strip(".") + "."
    return title.strip(".") + "."


def _undocumented_count(tree: ast.AST) -> int:
    """How many functions / classes / methods in ``tree`` lack a docstring."""
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, _DEF) and ast.get_docstring(node) is None
    )


def _collect_targets(tree: ast.AST, lines: list[str]) -> list[ast.AST]:
    """Every undocumented symbol that can be safely annotated in this pass.

    Skips a symbol whose next line already opens with a string literal (treated
    as documented) — mirrors the original guard — and any node whose line index
    is out of range for the source.
    """
    targets: list[ast.AST] = []
    for node in ast.walk(tree):
        if not isinstance(node, _DEF) or ast.get_docstring(node) is not None:
            continue
        lineno = node.lineno - 1
        if lineno >= len(lines):
            continue
        insert_at = lineno + 1
        if insert_at < len(lines) and lines[insert_at].strip().startswith('"""'):
            continue
        targets.append(node)
    return targets


def _insert_docstrings(
    lines: list[str], targets: list[ast.AST], title: str,
) -> tuple[str, list[str]]:
    """Insert one docstring per target, bottom-up, returning content + names.

    Processing highest line number first means every insertion leaves earlier
    line indices valid, so the whole file is documented in a single pass.
    """
    new_lines = list(lines)
    names: list[str] = []
    multiple = len(targets) > 1
    for node in sorted(targets, key=lambda n: n.lineno, reverse=True):
        lineno = node.lineno - 1
        body_indent = _get_indent(new_lines[lineno]) + "    "
        docstring = f'{body_indent}"""{_doc_text(node, title, multiple)}"""\n'
        insert_at = lineno + 1
        new_lines = new_lines[:insert_at] + [docstring] + new_lines[insert_at:]
        names.append(getattr(node, "name", "<symbol>"))
    names.reverse()  # report in source order
    return "".join(new_lines), names


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    lines = source.splitlines(keepends=True)
    targets = _collect_targets(tree, lines)
    if not targets:
        return None

    new_content, names = _insert_docstrings(lines, targets, title)

    # Self-validating: refuse the patch unless it re-parses AND the undocumented
    # count dropped by exactly the number of symbols we inserted — every target
    # we touched is now documented and nothing else shifted.
    try:
        new_tree = ast.parse(new_content)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    if _undocumented_count(new_tree) != _undocumented_count(tree) - len(targets):
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="add_docstring",
        rationale=[
            f"Added missing docstring to {name} in {rel_path}." for name in names
        ],
    )
