"""Mine git commit history for single-line Python expression changes.

Used by ``apex teach --from-git``: commits that touch exactly one expression
line in a ``.py`` file are candidates for rule learning — the before/after
pair feeds the same anti-unification engine as explicit examples.  Multi-line
hunks (refactors, additions) are skipped; only pure single-line fixes count.
Deterministic, stdlib + subprocess only.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess


def _is_expr(text: str) -> bool:
    """True if ``text`` parses as a standalone Python expression."""
    try:
        ast.parse(text, mode="eval")
    except (SyntaxError, RecursionError, MemoryError):
        return False
    return True


def _stmt_value(stmt: ast.stmt) -> ast.expr | None:
    """Return the value node of a single-line statement we can unwrap.

    Covers ``return EXPR``, ``x = EXPR``, annotated assigns, and bare
    expression statements; returns None for any other statement form.
    """
    if isinstance(stmt, ast.Return) and stmt.value is not None:
        return stmt.value
    if isinstance(stmt, ast.Assign) and stmt.targets:
        return stmt.value
    if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        return stmt.value
    if isinstance(stmt, ast.Expr):
        return stmt.value
    return None


def _unwrap_statement(stripped: str) -> str | None:
    """Unwrap a single-line statement to the source text of its value node."""
    try:
        tree = ast.parse(stripped, mode="exec")
    except (SyntaxError, RecursionError, MemoryError):
        return None
    if len(tree.body) != 1:
        return None
    value = _stmt_value(tree.body[0])
    if value is None:
        return None
    return ast.get_source_segment(stripped, value)


def _extract_expr(line: str) -> str | None:
    """Extract the expression part from a single Python line.

    Handles bare expressions, ``return EXPR``, ``x = EXPR``, annotated
    assigns, and expression-statement calls (e.g. ``cache.clear()``).
    Returns the expression text if it's independently parseable, else None.
    """
    stripped = line.strip()
    # Fast path: bare expression.
    if _is_expr(stripped):
        return stripped
    # Unwrap common single-line statement forms.
    seg = _unwrap_statement(stripped)
    if not seg:
        return None
    # Verify the extracted segment is itself a valid expression.
    if not _is_expr(seg):
        return None
    return seg


def _shas_from_log(log_stdout: str) -> list[str]:
    """Extract commit SHAs from ``git log --oneline`` output.

    Skips blank lines; the SHA is the first whitespace-delimited token.
    """
    shas: list[str] = []
    for line in log_stdout.splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        shas.append(parts[0])
    return shas


def _single_change(diff_stdout: str) -> tuple[str, str] | None:
    """Return the (removed, added) line pair from a ``--unified=0`` diff.

    Yields a pair only when exactly one line was removed and exactly one
    added (a clean single-line change); otherwise None.
    """
    removed = [ln[1:] for ln in diff_stdout.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    added = [ln[1:] for ln in diff_stdout.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    if len(removed) != 1 or len(added) != 1:
        return None  # multi-line change — not a clean single-expression fix
    return removed[0], added[0]


def _expr_pair(removed: str, added: str) -> tuple[str, str] | None:
    """Unwrap both lines to bare expressions, returning the pair if distinct.

    Returns None when either line is not a parseable expression or the two
    expressions are identical (no semantic change).
    """
    before_expr = _extract_expr(removed)
    after_expr = _extract_expr(added)
    if not before_expr or not after_expr or before_expr == after_expr:
        return None
    return before_expr, after_expr


def mine_git_pairs(project_root: str | Path,
                   max_commits: int = 50) -> list[tuple[str, str]]:
    """Return (before, after) expression-text pairs from the last
    ``max_commits`` commits that changed exactly one Python expression line.

    Each changed line is unwrapped from its statement context (``return``,
    assignment, expression-statement) to yield the bare expression.  This lets
    the rule engine see ``len(xs) == 0`` → ``not xs`` regardless of whether the
    change lived in a ``return`` or a bare condition expression.
    """
    root = str(project_root)
    log = subprocess.run(
        ["git", "log", "--oneline", f"-{max_commits}", "--", "*.py"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    if log.returncode != 0:
        return []

    pairs: list[tuple[str, str]] = []
    for sha in _shas_from_log(log.stdout):
        diff = subprocess.run(
            ["git", "diff", f"{sha}^..{sha}", "--unified=0", "--", "*.py"],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        if diff.returncode != 0:
            continue  # initial commit or merge commit — skip
        change = _single_change(diff.stdout)
        if change is None:
            continue
        pair = _expr_pair(*change)
        if pair is None:
            continue
        pairs.append(pair)
    return pairs
