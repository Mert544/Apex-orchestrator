"""On-demand code metrics for specific modules.

Where ``PythonStructureAnalyzer`` sweeps a whole tree, this computes a few cheap,
deterministic size/complexity numbers for *named* modules only — the subjects an
idea tree actually references. Those numbers ground the roadmap's effort estimate
in real code: a 600-line, branch-heavy module costs more to change than a tidy
30-line one, regardless of how the idea scored.

Stdlib-only (ast + line counting). Unreadable/unparseable files yield ``None``.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def hotspot_risk(complexity: int, fan_in: int, tests: int) -> float:
    """Risk score for a module: complexity x blast-radius / test coverage.

    High cyclomatic complexity and many importers raise it; linked tests lower
    it. Lives here (a stdlib-only metrics module) so both the hotspots report and
    the profiler can share it without an import cycle.
    """
    return round(complexity * (1 + fan_in) / (1 + tests), 2)

# AST node types counted as a branch (a cheap cyclomatic-complexity proxy).
_BRANCH_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.ExceptHandler,
    ast.With, ast.AsyncWith, ast.BoolOp, ast.IfExp,
    ast.comprehension,
)


@dataclass
class ModuleMetrics:
    path: str
    loc: int            # non-blank, non-comment-only source lines
    symbols: int        # top-level + nested functions and classes
    complexity: int     # branch-node count (cyclomatic-ish proxy)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodeMetrics:
    """Measure size/complexity for individual modules under a project root."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root)

    def for_module(self, rel_path: str) -> ModuleMetrics | None:
        """Measure one module by its project-relative path (e.g. ``app/x.py``)."""
        if not rel_path or not rel_path.endswith(".py"):
            return None
        path = self.root / rel_path
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        loc = sum(
            1 for line in source.splitlines()
            if (s := line.strip()) and not s.startswith("#")
        )

        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Still report the line count; structure is unknown.
            return ModuleMetrics(path=rel_path, loc=loc, symbols=0, complexity=0)

        symbols = 0
        complexity = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols += 1
            if isinstance(node, _BRANCH_NODES):
                complexity += 1
        return ModuleMetrics(path=rel_path, loc=loc, symbols=symbols, complexity=complexity)

    def for_modules(self, rel_paths: list[str]) -> dict[str, ModuleMetrics]:
        """Measure a batch of modules, skipping any that can't be read/parsed."""
        out: dict[str, ModuleMetrics] = {}
        for rel in dict.fromkeys(rel_paths):  # dedupe, preserve order
            m = self.for_module(rel)
            if m is not None:
                out[rel] = m
        return out
