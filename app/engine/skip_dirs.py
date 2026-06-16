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

__all__ = [
    "SKIPPED_DIRS",
    "is_skipped",
    "iter_source_files",
    "is_test_or_fixture_path",
    "is_test_or_fixture_name",
    "module_dotted_name",
]

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


def is_test_or_fixture_path(rel: Path) -> bool:
    """True for the project's own tests/fixtures, excluded from shipped surface.

    Operates on the canonical skip-set (:func:`is_skipped`) in addition to
    test/fixture path conventions, so a relative path that somehow crosses a
    skipped directory is excluded here too. Pure name/component check, so it is
    deterministic. Case-sensitive on directory markers."""
    if is_skipped(rel):
        return True
    parts = rel.parts
    if any(p in ("tests", "test", "fixtures", "fixture", "testdata") for p in parts):
        return True
    name = rel.name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def is_test_or_fixture_name(rel: Path) -> bool:
    """True if a project-relative path is test/fixture code (not shipped surface).

    Pure name/component check, so it is deterministic and case-insensitive on the
    directory markers. Covers ``tests``/``fixtures`` directories anywhere in the
    path, plus ``test_*.py`` / ``*_test.py`` / ``conftest.py`` filenames."""
    parts_lower = {part.lower() for part in rel.parts[:-1]}
    if "tests" in parts_lower or "fixtures" in parts_lower:
        return True
    stem = rel.stem.lower()
    name = rel.name.lower()
    return name == "conftest.py" or stem.startswith("test_") or stem.endswith("_test")


def module_dotted_name(path: Path, root: Path) -> str:
    """Stable dotted module name from a root-relative path (``app/x.py`` ->
    ``app.x``). Falls back to the bare path if ``path`` is outside ``root``."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    posix = rel.as_posix()
    if posix.endswith(".py"):
        posix = posix[:-3]
    return posix.replace("/", ".")
