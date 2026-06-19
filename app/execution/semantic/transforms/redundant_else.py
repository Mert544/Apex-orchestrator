"""Drop a redundant ``else`` after an ``if`` branch that always terminates.

When the ``if`` branch unconditionally ends in ``return`` / ``raise`` /
``continue`` / ``break``, control never falls through to the code after the
``if`` along that path, so the ``else:`` is dead structure: its body can be
dedented to follow the ``if`` with identical behaviour (a common readability /
"no-else-return" cleanup, pylint R1705/R1720).

The rewrite is intentionally conservative. It fires only when:

* the ``if`` body's **last** statement is a bare ``return`` / ``raise`` /
  ``continue`` / ``break`` — i.e. termination is unconditional and not buried
  inside a nested ``if`` / loop / ``try`` (where it might not run);
* there is exactly one ``else`` and **no** ``elif`` (an ``elif`` chain shares
  the ``if`` head and cannot be safely flattened by a pure dedent);
* every line of the ``else`` body is indented strictly past the ``else:`` and
  can be dedented by exactly the ``if``/``else`` indent step without colliding
  with the surrounding block.

It transforms a single ``if`` per call (the first eligible, top-to-bottom),
re-parses the result, and returns ``None`` if anything about the splice is
uncertain — it never emits a patch it cannot prove re-parses.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent

# Statements that, as the *last* statement of a block, hand control away
# unconditionally so the following ``else`` body becomes unreachable fall-through.
_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _is_real_else(node: ast.If) -> bool:
    """True iff ``node.orelse`` is a genuine ``else:`` block (not an ``elif``).

    Python represents ``elif`` as an ``orelse`` holding a single ``ast.If`` whose
    head sits on the same column as the ``else`` keyword would. A real ``else``
    has a body that starts indented *past* the ``if`` head; an ``elif``'s nested
    ``If`` starts at the ``if``'s own column. We treat the single-If-at-same-col
    case as ``elif`` and refuse it.
    """
    orelse = node.orelse
    if not orelse:
        return False
    if (len(orelse) == 1 and isinstance(orelse[0], ast.If)
            and orelse[0].col_offset == node.col_offset
            and orelse[0].lineno > (node.body[-1].end_lineno or node.body[-1].lineno)):
        return False  # elif chain
    return True


def _terminates(if_node: ast.If) -> bool:
    """True iff the ``if`` branch's last statement unconditionally terminates.

    Only a *direct* terminator counts. A terminator nested inside another
    ``if`` / loop / ``try`` / ``with`` may not execute on every path, so the
    ``else`` is not provably dead and we refuse.
    """
    body = if_node.body
    if not body:
        return False
    return isinstance(body[-1], _TERMINATORS)


def _elif_heads(tree: ast.Module) -> set[ast.If]:
    """Every ``If`` node that is actually the ``elif`` of an enclosing ``if``.

    Such a node shares its parent's ``if`` head line and cannot be flattened by a
    pure dedent without also rewriting the chain, so we exclude it entirely.
    """
    out: set[ast.If] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and not _is_real_else(node):
            # not _is_real_else -> orelse is the single-If elif form.
            if node.orelse:
                out.add(node.orelse[0])  # type: ignore[arg-type]
    return out


def _candidate(tree: ast.Module) -> ast.If | None:
    """First ``if`` (top-to-bottom) eligible for else-removal, or ``None``."""
    elif_heads = _elif_heads(tree)
    best: ast.If | None = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.If)
                and node not in elif_heads
                and _is_real_else(node)
                and _terminates(node)):
            if best is None or node.lineno < best.lineno:
                best = node
    return best


def _indent_step(lines: list[str], if_node: ast.If) -> str | None:
    """The indent the ``if`` body adds past the ``if`` head, e.g. ``"    "``.

    Returns ``None`` if the body indent does not extend the ``if`` indent (an
    unexpected layout the dedent cannot reason about).
    """
    if_indent = _get_indent(lines[if_node.lineno - 1])
    body_indent = _get_indent(lines[if_node.body[0].lineno - 1])
    step = body_indent[len(if_indent):]
    if not step or body_indent[:len(if_indent)] != if_indent:
        return None  # unexpected layout; refuse
    return step


def _find_else_kw(lines: list[str], if_node: ast.If, if_indent: str,
                  else_body_start: int) -> int | None:
    """Index of the ``else:`` keyword line, or ``None`` if not cleanly found.

    The keyword is the last non-blank line strictly before the body; it must be
    exactly ``else:`` at the ``if`` indent.
    """
    for i in range(else_body_start - 1, if_node.lineno - 1, -1):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "else:" and _get_indent(lines[i]) == if_indent:
            return i
        return None
    return None


def _gap_is_blank(lines: list[str], else_kw_idx: int, else_body_start: int) -> bool:
    """True iff only blank lines sit between ``else:`` and its first statement.

    A comment there has an ambiguous destination after a dedent, so the caller
    must refuse rather than relocate it.
    """
    return all(lines[i].strip() == "" for i in range(else_kw_idx + 1, else_body_start))


def _dedent_body(lines: list[str], if_indent: str, expected_body_indent: str,
                 else_body_start: int, else_body_end: int) -> list[str] | None:
    """Dedent the else-body lines by one step, or ``None`` if any line collides.

    Blank lines pass through unchanged; non-blank lines must start with the
    expected body indent so the dedent is exact rather than a guess.
    """
    out: list[str] = []
    for i in range(else_body_start, else_body_end + 1):
        line = lines[i]
        if line.strip() == "":
            out.append(line)                    # blank lines pass through as-is
            continue
        if not line.startswith(expected_body_indent):
            return None  # body not indented as expected; refuse rather than guess
        out.append(if_indent + line[len(expected_body_indent):])
    return out


def _dedent_else(lines: list[str], if_node: ast.If) -> list[str] | None:
    """Splice out the ``else:`` line and dedent its body by one indent step.

    Returns the rewritten lines, or ``None`` if any line of the construct does
    not fit the exact-indentation contract (so the caller refuses).
    """
    orelse = if_node.orelse
    first = orelse[0]
    last = orelse[-1]

    # 1-based AST line numbers -> 0-based indices.
    if_indent = _get_indent(lines[if_node.lineno - 1])
    step = _indent_step(lines, if_node)
    if step is None:
        return None

    else_body_start = first.lineno - 1          # 0-based, first else-body line
    else_body_end = (last.end_lineno or last.lineno) - 1  # 0-based, inclusive

    else_kw_idx = _find_else_kw(lines, if_node, if_indent, else_body_start)
    if else_kw_idx is None:
        return None  # could not locate a clean ``else:`` line; refuse

    if not _gap_is_blank(lines, else_kw_idx, else_body_start):
        return None  # comment in the gap; ambiguous destination, refuse

    dedented = _dedent_body(
        lines, if_indent, if_indent + step, else_body_start, else_body_end)
    if dedented is None:
        return None

    out: list[str] = []
    out.extend(lines[:else_kw_idx])             # everything up to (excl.) else:
    out.extend(lines[else_kw_idx + 1:else_body_start])  # blank lines between
    out.extend(dedented)
    out.extend(lines[else_body_end + 1:])       # remainder of the file
    return out


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    if_node = _candidate(tree)
    if if_node is None:
        return None

    lines = source.splitlines(keepends=True)
    new_lines = _dedent_else(lines, if_node)
    if new_lines is None:
        return None

    new_content = "".join(new_lines)
    if new_content == source:
        return None

    # Never emit a patch we cannot prove re-parses.
    try:
        ast.parse(new_content)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="remove_redundant_else",
        rationale=[
            f"Removed a redundant `else` after a terminating `if` branch in "
            f"{rel_path} (dead fall-through; behaviour-preserving)."
        ],
    )
