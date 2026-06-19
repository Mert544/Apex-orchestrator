"""Deterministic test-suite *balance* analyzer.

Where ``TestLinker`` answers "which modules have a linked test?", this answers
the blunter, project-wide question: **is the suite proportionate to the code it
guards?** A repo can have a test file per package and still be thin — 30 lines
of asserts over 3 000 lines of logic — or lopsided, with one giant package
carrying no tests at all. Those imbalances are what fragility and risk signals
should weigh, and a single ratio per package makes the gaps legible.

It measures, all by walking the tree exactly once via the shared
:func:`iter_source_files` (so worktree COPIES and ``__pycache__`` never count):

  - **LOC ratio** — test source lines over production source lines;
  - **file ratio** — test files over production files;
  - **function ratio** — ``test*`` functions over production functions;
  - **per-package density** — for each top-level package, its test-to-prod LOC
    ratio, so the under-tested packages sort to the top.

A *test file* is one whose project-relative path lives under a ``tests/``
directory (top-level or nested) OR whose basename matches the ``test_*.py`` /
``*_test.py`` convention; everything else parseable is production. LOC counts
non-blank, non-comment-only lines (the same rule as
:class:`~app.tools.code_metrics.CodeMetrics`).

Stdlib-only (``ast`` + line counting), pure, empty-safe (no division by zero),
and deterministic: same tree → same numbers, no clock/random/network.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import iter_source_files

__all__ = ["TestBalance", "analyze_test_balance", "is_test_file"]

# Ratios are unbounded in principle, but a package with prod code and a single
# trivially-large test would otherwise dwarf every honest gap. Cap the reported
# per-package ratio so the "most under-tested" ordering stays meaningful.
_RATIO_CAP = 10.0


def is_test_file(rel_path: str | Path) -> bool:
    """True if a project-relative path is a *test* file by convention.

    A path counts as a test when any directory component is ``tests`` (so both
    ``tests/test_x.py`` and ``app/foo/tests/x.py`` qualify) OR its basename
    matches ``test_*.py`` / ``*_test.py``. Pure name check — no disk access — so
    it is deterministic and safe on relative or absolute paths.
    """
    path = Path(rel_path)
    parts_lower = [part.lower() for part in path.parts]
    if "tests" in parts_lower:
        return True
    stem = path.stem.lower()
    return stem.startswith("test_") or stem.endswith("_test")


def _loc(source: str) -> int:
    """Non-blank, non-comment-only source lines (CodeMetrics' rule)."""
    return sum(
        1 for line in source.splitlines()
        if (s := line.strip()) and not s.startswith("#")
    )


def _function_count(source: str, *, tests_only: bool) -> int:
    """Count function/method definitions in ``source``.

    ``tests_only`` restricts to ``test*`` functions (the pytest convention used
    by :func:`app.tools.test_linker.count_test_functions`); otherwise every
    ``def``/``async def`` counts. Unparseable source contributes ``0``.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return 0
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not tests_only or node.name.startswith("test"):
                total += 1
    return total


def _top_package(rel: Path) -> str:
    """The top-level package name for a project-relative path.

    A file directly under the root (``setup.py``) maps to the sentinel
    ``"<root>"`` so it is never silently merged with a real package.
    """
    parts = rel.parts
    return parts[0] if len(parts) > 1 else "<root>"


def _ratio(test_loc: int, prod_loc: int) -> float:
    """Test/prod LOC ratio, empty-safe and capped.

    Zero production LOC yields ``0.0`` (a package with no prod code is not
    "under-tested" — there is nothing to test), and the result is clamped to
    :data:`_RATIO_CAP` so a thin-but-huge test file can't dominate the ordering.
    """
    if prod_loc <= 0:
        return 0.0
    return round(min(test_loc / prod_loc, _RATIO_CAP), 4)


@dataclass
class TestBalance:
    """A project's test-to-production balance.

    All counts are tree-wide; ``under_tested_packages`` ranks top-level packages
    by their LOC ratio ascending (the most under-tested first), and only
    includes packages that actually contain production code.
    """

    __test__ = False  # not a pytest test class

    test_loc: int = 0
    prod_loc: int = 0
    loc_ratio: float = 0.0          # test_loc / prod_loc, in [0, inf)
    test_files: int = 0
    prod_files: int = 0
    file_ratio: float = 0.0         # test_files / prod_files
    test_functions: int = 0
    prod_functions: int = 0
    function_ratio: float = 0.0     # test_functions / prod_functions
    under_tested_packages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_loc": self.test_loc,
            "prod_loc": self.prod_loc,
            "loc_ratio": self.loc_ratio,
            "test_files": self.test_files,
            "prod_files": self.prod_files,
            "file_ratio": self.file_ratio,
            "test_functions": self.test_functions,
            "prod_functions": self.prod_functions,
            "function_ratio": self.function_ratio,
            "under_tested_packages": [dict(p) for p in self.under_tested_packages],
        }


def analyze_test_balance(root: str | Path, max_files: int = 1000) -> TestBalance:
    """Measure the test-to-production balance of the project under ``root``.

    Walks every ``*.py`` file once (skipping VCS/cache/worktree dirs via
    :func:`iter_source_files`), capping at ``max_files`` for bounded cost on huge
    trees. Returns a :class:`TestBalance` with tree-wide LOC/file/function ratios
    and a per-top-level-package under-tested ranking. Empty (or all-unparseable)
    trees yield an all-zero, division-safe result.
    """
    root = Path(root)

    test_loc = prod_loc = 0
    test_files = prod_files = 0
    test_functions = prod_functions = 0
    # Per top-level package: accumulated [prod_loc, test_loc].
    pkg_prod: dict[str, int] = {}
    pkg_test: dict[str, int] = {}

    files = list(iter_source_files(root))
    if max_files >= 0:
        files = files[:max_files]

    for path in files:
        rel = path.relative_to(root)
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        loc = _loc(source)
        pkg = _top_package(rel)

        if is_test_file(rel):
            test_loc += loc
            test_files += 1
            test_functions += _function_count(source, tests_only=True)
            pkg_test[pkg] = pkg_test.get(pkg, 0) + loc
        else:
            prod_loc += loc
            prod_files += 1
            prod_functions += _function_count(source, tests_only=False)
            pkg_prod[pkg] = pkg_prod.get(pkg, 0) + loc

    # Per-package ranking: only packages with production code can be
    # under-tested. Sort ascending by ratio, then by package name for a stable,
    # deterministic tie-break.
    under_tested: list[dict[str, Any]] = []
    for pkg in sorted(pkg_prod):
        p_loc = pkg_prod[pkg]
        t_loc = pkg_test.get(pkg, 0)
        under_tested.append({
            "package": pkg,
            "prod_loc": p_loc,
            "test_loc": t_loc,
            "ratio": _ratio(t_loc, p_loc),
        })
    under_tested.sort(key=lambda row: (row["ratio"], row["package"]))

    return TestBalance(
        test_loc=test_loc,
        prod_loc=prod_loc,
        loc_ratio=_ratio(test_loc, prod_loc),
        test_files=test_files,
        prod_files=prod_files,
        file_ratio=_ratio(test_files, prod_files),
        test_functions=test_functions,
        prod_functions=prod_functions,
        function_ratio=_ratio(test_functions, prod_functions),
        under_tested_packages=under_tested,
    )
