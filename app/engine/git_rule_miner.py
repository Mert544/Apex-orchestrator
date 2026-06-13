"""Mine git commit history for single-line Python expression changes.

Used by ``apex teach --from-git``: commits that touch exactly one expression
line in a ``.py`` file are candidates for rule learning — the before/after
pair feeds the same anti-unification engine as explicit examples.  Multi-line
hunks (refactors, additions) are skipped; only pure single-line fixes count.
Deterministic, stdlib + subprocess only.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path


def _extract_expr(line: str) -> str | None:
    """Extract the expression part from a single Python line.

    Handles bare expressions, ``return EXPR``, ``x = EXPR``, annotated
    assigns, and expression-statement calls (e.g. ``cache.clear()``).
    Returns the expression text if it's independently parseable, else None.
    """
    stripped = line.strip()
    # Fast path: bare expression.
    try:
        ast.parse(stripped, mode="eval")
        return stripped
    except SyntaxError:
        pass
    # Unwrap common single-line statement forms.
    try:
        tree = ast.parse(stripped, mode="exec")
    except SyntaxError:
        return None
    if len(tree.body) != 1:
        return None
    stmt = tree.body[0]
    if isinstance(stmt, ast.Return) and stmt.value is not None:
        seg = ast.get_source_segment(stripped, stmt.value)
    elif isinstance(stmt, ast.Assign) and stmt.targets:
        seg = ast.get_source_segment(stripped, stmt.value)
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        seg = ast.get_source_segment(stripped, stmt.value)
    elif isinstance(stmt, ast.Expr):
        seg = ast.get_source_segment(stripped, stmt.value)
    else:
        return None
    if not seg:
        return None
    # Verify the extracted segment is itself a valid expression.
    try:
        ast.parse(seg, mode="eval")
    except SyntaxError:
        return None
    return seg


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
    for line in log.stdout.splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        sha = parts[0]
        diff = subprocess.run(
            ["git", "diff", f"{sha}^..{sha}", "--unified=0", "--", "*.py"],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        if diff.returncode != 0:
            continue  # initial commit or merge commit — skip
        removed = [ln[1:] for ln in diff.stdout.splitlines()
                   if ln.startswith("-") and not ln.startswith("---")]
        added = [ln[1:] for ln in diff.stdout.splitlines()
                 if ln.startswith("+") and not ln.startswith("+++")]
        if len(removed) != 1 or len(added) != 1:
            continue  # multi-line change — not a clean single-expression fix
        before_expr = _extract_expr(removed[0])
        after_expr = _extract_expr(added[0])
        if not before_expr or not after_expr or before_expr == after_expr:
            continue
        pairs.append((before_expr, after_expr))
    return pairs
