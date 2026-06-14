"""Canonical directory-name exclusions for every project-tree walk.

A single source of truth so no walker re-derives its own — inevitably
inconsistent — skip-set. Before this module the exclusion was copy-pasted across
a dozen walkers with subtly different contents, and the omission that bit Apex
hardest was ``.claude/``: it holds agent git worktrees, which are FULL repo
copies. A walk that descends into them re-counts every module, collides
test-file basenames (eight copies of ``test_foo.py`` break pytest collection),
near-hangs whole-repo analyzers, and — worst — can make a capped analyzer grade
the worktree COPIES instead of the real code (``.claude`` sorts early, so a
``rglob(...)[:max_files]`` slice fills up with copies first).

Excluded names, by category:

  - VCS / caches: ``.git``, ``__pycache__``;
  - Apex metadata / worktrees: ``.apex``, ``.epistemic``, ``.claude``;
  - virtualenvs: ``.venv``, ``venv``;
  - third-party / build output: ``node_modules``, ``dist``, ``build``.

Deterministic, stdlib-only. Import :data:`SKIPPED_DIRS` for a membership set or
call :func:`is_skipped` to test a path.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

__all__ = ["SKIPPED_DIRS", "is_skipped", "iter_source_files"]

SKIPPED_DIRS = frozenset({
    ".git", "__pycache__", ".apex", ".epistemic", ".claude",
    ".venv", "venv", "node_modules", "dist", "build",
})


def is_skipped(path: str | Path) -> bool:
    """True if ANY path component is an excluded directory name.

    Works on relative or absolute paths and on file or directory paths — it is a
    pure name check over ``Path(path).parts``, so ``app/x.py`` is kept while
    ``.claude/worktrees/agent-1/app/x.py`` and ``app/__pycache__/x.py`` are
    skipped."""
    return bool(set(Path(path).parts) & SKIPPED_DIRS)


def iter_source_files(root: str | Path, pattern: str = "*.py") -> Iterable[Path]:
    """Yield every ``root``-relative file matching ``pattern`` whose path crosses
    no excluded directory — the safe replacement for a bare ``root.rglob(...)``.

    Deterministic: results are sorted, so a downstream ``[:max_files]`` cap is
    reproducible (and never silently fills with worktree copies)."""
    root = Path(root)
    return sorted(p for p in root.rglob(pattern) if not is_skipped(p.relative_to(root)))
