from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def _is_rewritable_dict_call(node: ast.Call) -> bool:
    """Return True only when ``node`` is a safe ``dict(a=1, b=2)`` call.

    Safety conditions (all must hold):

    * the callee is the bare builtin name ``dict`` (an ``ast.Name``);
    * there are NO positional args (``dict(x, a=1)`` is refused);
    * there is at least one keyword (``dict()`` empty is refused — idiomatic);
    * there is NO ``**`` unpacking (``dict(**other)`` keyword with ``arg is None``);
    * every keyword name is a valid identifier (always true for real kwargs).
    """
    func = node.func
    if not isinstance(func, ast.Name) or func.id != "dict":
        return False
    if node.args:
        # any positional argument (including *args splat) → refuse
        return False
    if not node.keywords:
        # dict() — empty, leave as-is
        return False
    for kw in node.keywords:
        if kw.arg is None:
            # **unpacking → refuse
            return False
        if not isinstance(kw.arg, str) or not kw.arg.isidentifier():
            return False
    return True


def _render_literal(node: ast.Call, source: str) -> str | None:
    """Build the ``{"a": value, ...}`` text preserving each value verbatim."""
    parts: list[str] = []
    for kw in node.keywords:
        value_text = ast.get_source_segment(source, kw.value)
        if value_text is None:
            return None
        parts.append(f'"{kw.arg}": {value_text}')
    return "{" + ", ".join(parts) + "}"


def _candidate_replacement(
    node: ast.AST, source: str
) -> tuple[int, int, str] | None:
    """Return ``(start, end, literal)`` for a rewritable ``dict(...)`` call.

    Returns ``None`` for any node that is not a safe, splice-able candidate:
    a non-call, an unsafe call, a value we cannot render, or a call whose
    computed offsets do not splice back to its exact source segment.
    """
    if not isinstance(node, ast.Call) or not _is_rewritable_dict_call(node):
        return None
    literal = _render_literal(node, source)
    if literal is None:
        return None
    call_text = ast.get_source_segment(source, node)
    if call_text is None:
        return None
    start = _node_offset(source, node)
    if start is None:
        return None
    end = start + len(call_text)
    if source[start:end] != call_text:
        return None
    return start, end, literal


def _collect_replacements(tree: ast.AST, source: str) -> list[tuple[int, int, str]]:
    """Gather every splice-able ``dict(...)`` rewrite from ``tree``.

    Use offsets so we can splice the original text and preserve value
    formatting exactly. Process outermost-first via ``ast.walk``.
    """
    replacements: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        candidate = _candidate_replacement(node, source)
        if candidate is not None:
            replacements.append(candidate)
    return replacements


def _splice(source: str, replacements: list[tuple[int, int, str]]) -> str:
    """Apply replacements to ``source``, splicing in reverse source order.

    Replacing right-to-left keeps earlier offsets valid as spans are swapped.
    """
    new_source = source
    for start, end, literal in sorted(replacements, key=lambda item: item[0], reverse=True):
        new_source = new_source[:start] + literal + new_source[end:]
    return new_source


def apply(rel_path: str, source: str, title: str = "") -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    replacements = _collect_replacements(tree, source)
    if not replacements:
        return None

    new_source = _splice(source, replacements)
    if new_source == source:
        return None

    # Re-parse: never emit content we cannot parse back.
    try:
        ast.parse(new_source)
    except SyntaxError:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="dict_literal",
        rationale=[
            f"Rewrote {len(replacements)} dict() call(s) to dict literal(s) in {rel_path}."
        ],
    )


def _node_offset(source: str, node: ast.AST) -> int | None:
    """Convert a node's (lineno, col_offset) into an absolute string offset."""
    lineno = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    if lineno is None or col is None:
        return None
    # col_offset is a byte offset within the line; compute line start offsets.
    line_start = 0
    current_line = 1
    while current_line < lineno:
        idx = source.find("\n", line_start)
        if idx == -1:
            return None
        line_start = idx + 1
        current_line += 1
    # Decode the byte column to a character offset on the line.
    line_bytes = source[line_start:].encode("utf-8")
    prefix = line_bytes[:col].decode("utf-8", errors="strict")
    return line_start + len(prefix)
