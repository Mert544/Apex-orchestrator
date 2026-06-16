"""Constant-fold an adjacent string-literal concatenation: ``"a" + "b"`` -> ``"ab"``.

Two string literals joined with ``+`` are a pure compile-time constant. Folding
them changes nothing at runtime — it is the one rewrite of string ``+`` that is
unambiguously safe, because BOTH operands are already known string constants.

The rewrite is deliberately paranoid. It fires ONLY when every one of these holds
for a ``BinOp`` with an ``Add`` operator, and REFUSES otherwise:

  * both operands are ``ast.Constant`` whose ``.value`` is a ``str`` — never a
    Name, Call, number, bytes, f-string (``JoinedStr``), or nested ``BinOp``;
  * neither literal contains an escape, newline, backslash, or a quote character,
    and every character is printable — so the folded value can be re-emitted
    verbatim without re-deriving escapes;
  * both literals use the SAME simple quote (both ``"`` or both ``'``) — a mixed
    pair (``"a" + 'b'``) refuses rather than guess a quote;
  * the source segments are simple ``"<text>"`` / ``'<text>'`` forms with no
    prefix (``r``, ``b``, ``f``, ``u``) and the whole BinOp is on ONE line.

``+=`` is an ``AugAssign``, never a ``BinOp`` operand here, so it is never
touched. The folded literal is emitted as ``<quote><a><b><quote>``; the result is
re-parsed and its ``ast.literal_eval`` is asserted equal to the original
concatenation's value, so the file is never corrupted.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult

_QUOTES = ("'", '"')


def _is_str_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _safe_literal(segment: str | None) -> tuple[str, str] | None:
    """Return ``(quote, inner_text)`` for a simple, escape-free string literal.

    Refuses anything with a string prefix, mismatched/odd quoting, escapes,
    newlines, backslashes, embedded quotes, or non-printable characters.
    """
    if segment is None:
        return None
    if len(segment) < 2:
        return None
    quote = segment[0]
    if quote not in _QUOTES:
        return None  # has a prefix (r/b/f/u) or is a triple/odd quote
    if segment[-1] != quote:
        return None
    inner = segment[1:-1]
    # No escapes, no embedded quotes, no newlines/backslashes, printable only.
    if "\\" in inner or "\n" in inner or "\r" in inner:
        return None
    if quote in inner:
        return None
    if not inner.isprintable():
        return None
    return quote, inner


def _fold(node: ast.BinOp, source: str) -> tuple[str, str] | None:
    """Return ``(quote, folded_inner)`` if ``node`` is a foldable str concat."""
    if not isinstance(node.op, ast.Add):
        return None
    left, right = node.left, node.right
    if not (_is_str_constant(left) and _is_str_constant(right)):
        return None
    # Single line only — keeps the splice exact and rules out multi-line spans.
    if node.lineno != node.end_lineno:
        return None

    left_seg = ast.get_source_segment(source, left)
    right_seg = ast.get_source_segment(source, right)
    left_parts = _safe_literal(left_seg)
    right_parts = _safe_literal(right_seg)
    if left_parts is None or right_parts is None:
        return None

    lquote, ltext = left_parts
    rquote, rtext = right_parts
    if lquote != rquote:
        return None  # mixed quotes — refuse rather than guess

    folded_inner = ltext + rtext
    # The folded text must round-trip in the same quote with no new escaping.
    if lquote in folded_inner or "\\" in folded_inner:
        return None
    return lquote, folded_inner


def _targets(tree: ast.Module, source: str) -> list[tuple[ast.BinOp, str, str]]:
    out: list[tuple[ast.BinOp, str, str]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp):
            folded = _fold(n, source)
            if folded is not None:
                out.append((n, folded[0], folded[1]))
    return out


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    nodes = _targets(tree, source)
    if not nodes:
        return None

    lines = source.splitlines(keepends=True)
    changed = 0
    # Rightmost-first so splicing one node never shifts an earlier node's columns.
    for node, quote, folded_inner in sorted(
        nodes, key=lambda t: (t[0].lineno, t[0].col_offset), reverse=True
    ):
        li = node.lineno - 1
        if li >= len(lines):
            continue
        line = lines[li]
        start = node.col_offset
        end = node.end_col_offset or 0
        if end <= start or end > len(line):
            continue
        new_literal = f"{quote}{folded_inner}{quote}"
        # Value-equivalence: the new literal must evaluate to the concatenation
        # of the two originals. If not, refuse this splice entirely.
        try:
            new_value = ast.literal_eval(new_literal)
        except (ValueError, SyntaxError):
            continue
        assert isinstance(node.left, ast.Constant)
        assert isinstance(node.right, ast.Constant)
        if new_value != node.left.value + node.right.value:
            continue
        lines[li] = line[:start] + new_literal + line[end:]
        changed += 1

    if changed == 0:
        return None

    new_content = "".join(lines)
    if new_content == source:
        return None
    # Never corrupt the file: a spliced result that won't parse is discarded.
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
        transform_type="fold_string_concat",
        rationale=[
            f"Folded {changed} adjacent string-literal concatenation(s) "
            f'(`"a" + "b"` -> `"ab"`) in {rel_path} (constant fold, value-preserving).'
        ],
    )
