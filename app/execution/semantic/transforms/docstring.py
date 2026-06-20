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


def _body_insertion(node: ast.AST, lines: list[str]) -> tuple[int, str] | None:
    """Where a docstring becomes ``node``'s first body statement.

    Returns ``(insert_at, body_indent)`` where ``insert_at`` is the 0-based line
    index the docstring line is spliced *before* (so it lands as the first body
    statement, after the full — possibly multi-line — ``def ...:`` / ``class
    ...:`` header) and ``body_indent`` is the leading whitespace each body
    statement carries. Returns ``None`` when the node has no body or its
    positions point past the source.

    The body's true start is taken from the AST: the first body statement's
    ``lineno``/``col_offset``. That is robust to multi-line signatures,
    decorators, a header spanning several lines, and blank-line gaps between the
    header and the first statement — none of which a ``node.lineno + 1`` heuristic
    handles. The docstring is inserted on its own line *before* that first
    statement, at the statement's own indentation, so the body reads
    ``header:`` → docstring → original first statement.
    """
    body = getattr(node, "body", None)
    if not body:
        return None
    first = body[0]
    first_lineno = getattr(first, "lineno", None)
    if first_lineno is None or first_lineno - 1 >= len(lines):
        return None
    first_line = lines[first_lineno - 1]
    col = getattr(first, "col_offset", None)
    # Prefer the actual indentation of the first body statement's line; fall back
    # to col_offset (a byte offset, but body indent is ASCII whitespace).
    indent = _get_indent(first_line)
    if not indent and isinstance(col, int) and col > 0:
        indent = first_line[:col]
    return first_lineno - 1, indent


def _collect_targets(tree: ast.AST, lines: list[str]) -> list[ast.AST]:
    """Every undocumented symbol that can be safely annotated in this pass.

    A node is skipped when it has no usable body insertion point, or when the
    first body statement is already a string-literal expression on its own line
    (belt-and-braces with ``ast.get_docstring``; keeps the pass idempotent).
    """
    targets: list[ast.AST] = []
    for node in ast.walk(tree):
        if not isinstance(node, _DEF) or ast.get_docstring(node) is not None:
            continue
        spot = _body_insertion(node, lines)
        if spot is None:
            continue
        insert_at, _indent = spot
        if lines[insert_at].strip().startswith(('"""', "'''", 'r"""', "r'''")):
            continue
        targets.append(node)
    return targets


def _insert_docstrings(
    lines: list[str], targets: list[ast.AST], title: str,
) -> tuple[str, list[str]]:
    """Insert one docstring per target as its first body statement, bottom-up.

    For each target we splice the docstring line *before* the first body
    statement (computed from the AST, so multi-line signatures / decorators /
    blank-line gaps are handled correctly) at that statement's indentation.
    Processing the highest insertion line first keeps earlier line indices valid,
    so the whole file is documented in one pass.
    """
    new_lines = list(lines)
    multiple = len(targets) > 1
    placements: list[tuple[int, str, str]] = []  # (insert_at, doc_line, name)
    for node in targets:
        spot = _body_insertion(node, lines)
        if spot is None:
            continue
        insert_at, body_indent = spot
        doc = f'{body_indent}"""{_doc_text(node, title, multiple)}"""\n'
        placements.append((insert_at, doc, getattr(node, "name", "<symbol>")))

    names = [name for _at, _doc, name in sorted(placements, key=lambda p: p[0])]
    # Splice from the bottom of the file upward so earlier indices stay valid.
    for insert_at, doc, _name in sorted(
        placements, key=lambda p: p[0], reverse=True
    ):
        new_lines = new_lines[:insert_at] + [doc] + new_lines[insert_at:]
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
