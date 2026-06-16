"""Remove statically-unreachable code, conservatively.

Statements that follow an *unconditional* ``return`` / ``raise`` / ``break`` /
``continue`` at the SAME block level can never execute — the terminator always
leaves the suite first. This transform deletes exactly those dead statements,
and nothing else.

The bar for removal is deliberately high. We refuse (leave the suite untouched)
whenever deleting could lose something a human might still want:

* a nested ``def`` / ``async def`` / ``class`` — it may be imported or patched
  in via ``module.Inner`` even though it is unreachable as a statement;
* a ``global`` / ``nonlocal`` declaration — these have binding side effects that
  outlive the (never-run) line;
* a ``#`` comment anywhere in the span we would delete — silently dropping a
  comment is a surprise, so we back off instead.

Everything is AST-driven for detection and line-based for the edit, then the
result is re-parsed. If it does not parse, or nothing changed, we return
``None`` — the file is never corrupted.
"""

from __future__ import annotations

import ast
import tokenize
from io import StringIO

from ..result import SemanticPatchResult

_TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # Map every source line to True if a comment token starts on it. Lexical, so
    # a ``#`` inside a string literal is correctly NOT treated as a comment.
    comment_lines = _comment_lines(source)
    if comment_lines is None:
        return None  # could not tokenize — refuse rather than guess

    # (first_removed_lineno, last_removed_lineno) spans, 1-based inclusive.
    spans: list[tuple[int, int]] = []
    for suite in _iter_suites(tree):
        span = _dead_span(suite, comment_lines)
        if span is not None:
            spans.append(span)

    if not spans:
        return None

    new_content = _drop_spans(source, spans)
    if new_content is None or new_content == source:
        return None

    try:
        ast.parse(new_content)
    except SyntaxError:
        return None  # never hand back something that won't parse

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="remove_unreachable_code",
        rationale=[
            f"Removed statically-unreachable statement(s) after an unconditional "
            f"return/raise/break/continue in {rel_path}."
        ],
    )


def _comment_lines(source: str) -> set[int] | None:
    """Set of 1-based line numbers on which a comment token begins, or None."""
    out: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                out.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return out


def _iter_suites(tree: ast.Module):
    """Yield every statement-suite (list[stmt]) that forms a real block.

    A terminator only kills the rest of *its own* suite, so we examine each suite
    independently: function/class bodies, loop ``body``/``orelse``, if/with/try
    branches, etc. Module top-level is excluded — ``return``/``break`` are not
    valid there and a bare ``raise`` at module scope ending the file is a corner
    we simply do not touch.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Module):
            continue  # skip the module's own top-level body
        for attr in ("body", "orelse", "finalbody"):
            suite = getattr(node, attr, None)
            if isinstance(suite, list) and suite and all(
                isinstance(s, ast.stmt) for s in suite
            ):
                yield suite


def _terminator_index(suite: list[ast.stmt]) -> int | None:
    """Index of the first unconditional terminator that has dead code after it.

    None when no terminator exists, or it is already the suite's last statement.
    """
    for i, stmt in enumerate(suite):
        if isinstance(stmt, _TERMINATORS):
            return i if i != len(suite) - 1 else None
    return None


def _has_unsafe_stmt(dead: list[ast.stmt]) -> bool:
    """True if any dead statement nests a def/class or a binding declaration.

    Dropping these could lose something importable/patchable or with binding
    side effects, so the caller must back off when this holds.
    """
    unsafe = (
        ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Global, ast.Nonlocal
    )
    for stmt in dead:
        for sub in ast.walk(stmt):
            if isinstance(sub, unsafe):
                return True
    return False


def _span_bounds(
    terminator: ast.stmt, dead: list[ast.stmt]
) -> tuple[int, int] | None:
    """The (first, last) deletable line span, or None if it is empty.

    Starts on the line AFTER the terminator's last line — sweeping up orphaned
    blank lines and any comment sitting between the terminator and the dead code
    — and runs through the last dead statement's last line.
    """
    first = (terminator.end_lineno or terminator.lineno) + 1
    last = dead[-1].end_lineno or dead[-1].lineno
    return (first, last) if first <= last else None


def _span_has_comment(span: tuple[int, int], comment_lines: set[int]) -> bool:
    """True if any comment begins inside the inclusive ``span``."""
    first, last = span
    return any(first <= ln <= last for ln in comment_lines)


def _dead_span(
    suite: list[ast.stmt], comment_lines: set[int]
) -> tuple[int, int] | None:
    """The (first, last) source-line span of unreachable tail statements, or None.

    Returns None when the suite has no unconditional terminator before its end,
    or when any safety rule forbids the removal.
    """
    term_idx = _terminator_index(suite)
    if term_idx is None:
        return None

    dead = suite[term_idx + 1:]
    if _has_unsafe_stmt(dead):
        return None

    span = _span_bounds(suite[term_idx], dead)
    if span is None or _span_has_comment(span, comment_lines):
        return None

    return span


def _drop_spans(source: str, spans: list[tuple[int, int]]) -> str | None:
    """Delete the given 1-based inclusive line spans from ``source``."""
    lines = source.splitlines(keepends=True)
    total = len(lines)
    remove: set[int] = set()
    for first, last in spans:
        if first < 1 or last > total or first > last:
            return None  # span out of range — bail rather than mangle
        for ln in range(first, last + 1):
            remove.add(ln)
    if not remove:
        return None
    kept = [line for i, line in enumerate(lines, start=1) if i not in remove]
    return "".join(kept)
