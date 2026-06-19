"""Collapse a redundant nested ``if`` into a single ``and`` guard.

``if A:\n    if B:\n        BODY`` is exactly equivalent to ``if A and B:\n
BODY`` — both evaluate ``A`` first and only test ``B`` (and run ``BODY``) when
``A`` is truthy, because ``and`` short-circuits identically to the nesting.
The flattened form is shallower and easier to read.

This transform is deliberately *conservative*. It rewrites the outer ``if``
only when every one of these holds (otherwise it returns ``None``):

* the outer ``if`` body is **exactly** the single inner ``if`` and nothing
  else (no sibling statements before or after it),
* the inner statement is a plain ``ast.If`` with **no** ``else``/``elif``
  (``orelse`` is empty),
* the outer ``if`` itself has **no** ``else``/``elif`` (``orelse`` is empty),
* neither header spans multiple lines (so the splice stays exact),
* the inner header immediately follows the outer one — a comment or other text
  between the two headers would be lost, so any such case is refused,
* the inner header sits exactly one indentation step deeper than the outer,
* neither header carries an inline body or trailing comment after its ``:``.

Both conditions are wrapped in parentheses before being joined with ``and`` so
operator precedence can never be altered (``A or C`` + ``B`` becomes
``(A or C) and B``, never ``A or C and B``). The candidate output is re-parsed
and structurally re-checked against the intended flattening; if the result does
not parse or does not match, the transform refuses rather than risk corrupting
the file.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def _is_mergeable(node: ast.If) -> ast.If | None:
    """Return the inner ``If`` if ``node`` is a safe merge target, else ``None``."""
    # Outer must have no else/elif and a body of exactly one statement.
    if node.orelse:
        return None
    if len(node.body) != 1:
        return None
    inner = node.body[0]
    if not isinstance(inner, ast.If):
        return None
    # Inner must have no else/elif.
    if inner.orelse:
        return None
    # Single-line headers only, so the textual splice is exact.
    if node.test.lineno != node.test.end_lineno:
        return None
    if inner.test.lineno != inner.test.end_lineno:
        return None
    return inner


def _condition_src(lines: list[str], test: ast.expr) -> str | None:
    """Exact source text of a single-line condition expression, or ``None``."""
    li = test.lineno - 1
    if li < 0 or li >= len(lines):
        return None
    raw = lines[li]
    line = raw.splitlines()[0] if raw else ""
    start = test.col_offset
    end = test.end_col_offset
    if end is None or start < 0 or end > len(line) or end <= start:
        return None
    return line[start:end]


def _intended_dump(node: ast.If, inner: ast.If) -> str:
    """``ast.dump`` of the flattening we intend to produce, for verification."""
    merged_test = ast.BoolOp(op=ast.And(), values=[node.test, inner.test])
    merged = ast.If(test=merged_test, body=list(inner.body), orelse=[])
    module = ast.Module(body=[merged], type_ignores=[])
    ast.fix_missing_locations(module)
    return ast.dump(module)


def _line_indent(line: str) -> str:
    """Leading-whitespace prefix of ``line``."""
    return line[: len(line) - len(line.lstrip())]


def _headers_adjacent(lines: list[str], outer_hdr_idx: int,
                      inner_hdr_idx: int) -> bool:
    """Both header indices are in range and the inner immediately follows the outer."""
    if not (0 <= outer_hdr_idx < inner_hdr_idx < len(lines)):
        return False
    # The inner header must immediately follow the outer one. Anything between
    # them (a comment, say) would be silently dropped, so refuse.
    return inner_hdr_idx == outer_hdr_idx + 1


def _header_tail_ok(line: str, test: ast.expr) -> bool:
    """The header carries nothing after the test besides ``:`` and whitespace."""
    if test.end_col_offset is None:
        return False
    tail = line.splitlines()[0][test.end_col_offset:].strip()
    return tail == ":"


def _merged_body_lines(lines: list[str], inner: ast.If, inner_hdr_idx: int,
                       outer_indent: str, inner_indent: str) -> list[str] | None:
    """Inner-``if`` body dedented by one step, or ``None`` on an unexpected shape."""
    # Body lines: everything inside the inner `if`, dedented by one step.
    body_start = inner_hdr_idx + 1
    body_end = inner.end_lineno or inner.lineno  # inclusive 1-based -> exclusive slice
    body_lines: list[str] = []
    for raw in lines[body_start:body_end]:
        if raw.strip() == "":
            body_lines.append(raw)                # keep blank lines verbatim
            continue
        if not raw.startswith(inner_indent):
            return None                           # unexpected shape — refuse
        body_lines.append(outer_indent + raw[len(inner_indent):])
    return body_lines


def _verify_candidate(candidate: str, outer_hdr_idx: int,
                      node: ast.If, inner: ast.If) -> bool:
    """Re-parse ``candidate`` and confirm the merged ``if`` matches the intended flatten."""
    # Re-parse: never emit anything that does not compile.
    try:
        new_tree = ast.parse(candidate)
    except (SyntaxError, RecursionError, MemoryError):
        return False

    # Structural verification: the merged `if` must match the intended flatten.
    target = None
    for n in ast.walk(new_tree):
        if isinstance(n, ast.If) and n.lineno - 1 == outer_hdr_idx:
            target = n
            break
    if target is None:
        return False
    got = ast.Module(body=[ast.If(test=target.test, body=list(target.body), orelse=[])], type_ignores=[])
    ast.fix_missing_locations(got)
    return _intended_dump(node, inner) == ast.dump(got)


def _indents_compatible(outer_indent: str, inner_indent: str) -> bool:
    """Inner header sits exactly one (or more) indentation steps deeper than outer."""
    return inner_indent.startswith(outer_indent) and len(inner_indent) > len(outer_indent)


def _merged_header(lines: list[str], outer_line: str, inner_line: str,
                   outer_indent: str, node: ast.If, inner: ast.If) -> str | None:
    """Validate conditions/tails and build the merged header line, or ``None``."""
    a_src = _condition_src(lines, node.test)
    b_src = _condition_src(lines, inner.test)
    if a_src is None or b_src is None:
        return None
    # Refuse if either header carries anything after the test besides `:` and
    # whitespace (guards against inline bodies / trailing comments on the header).
    if not _header_tail_ok(outer_line, node.test) or not _header_tail_ok(inner_line, inner.test):
        return None
    newline = outer_line[len(outer_line.rstrip("\r\n")):] or "\n"
    return f"{outer_indent}if ({a_src}) and ({b_src}):{newline}"


def _try_merge_one(source: str, lines: list[str], node: ast.If) -> str | None:
    """Produce flattened source for one outer ``if``, or ``None`` to refuse."""
    inner = _is_mergeable(node)
    if inner is None:
        return None

    outer_hdr_idx = node.lineno - 1            # 0-based line of `if A:`
    inner_hdr_idx = inner.lineno - 1           # 0-based line of `    if B:`
    if not _headers_adjacent(lines, outer_hdr_idx, inner_hdr_idx):
        return None

    outer_line = lines[outer_hdr_idx]
    inner_line = lines[inner_hdr_idx]
    outer_indent = _line_indent(outer_line)
    inner_indent = _line_indent(inner_line)
    if not _indents_compatible(outer_indent, inner_indent):
        return None

    merged_header = _merged_header(lines, outer_line, inner_line, outer_indent, node, inner)
    if merged_header is None:
        return None

    body_lines = _merged_body_lines(lines, inner, inner_hdr_idx, outer_indent, inner_indent)
    if body_lines is None:
        return None
    body_end = inner.end_lineno or inner.lineno

    candidate = "".join(
        lines[:outer_hdr_idx] + [merged_header] + body_lines + lines[body_end:]
    )
    return _accept_candidate(candidate, source, outer_hdr_idx, node, inner)


def _accept_candidate(candidate: str, source: str, outer_hdr_idx: int,
                      node: ast.If, inner: ast.If) -> str | None:
    """Return ``candidate`` if it differs from source and verifies, else ``None``."""
    if candidate == source or not _verify_candidate(candidate, outer_hdr_idx, node, inner):
        return None
    return candidate


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    lines = source.splitlines(keepends=True)

    # Topmost-first: merge a single nested pair per call so the output is
    # deterministic and we never reason about shifted line numbers.
    candidates = [n for n in ast.walk(tree) if isinstance(n, ast.If)]
    candidates.sort(key=lambda n: (n.lineno, n.col_offset))
    for node in candidates:
        merged = _try_merge_one(source, lines, node)
        if merged is None:
            continue
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": merged,
                "expected_old_content": source,
            }],
            transform_type="merge_nested_if",
            rationale=[
                f"Collapsed a redundant nested `if` into a single `and` guard in "
                f"{rel_path} (behaviour-preserving; short-circuit identical)."
            ],
        )
    return None
