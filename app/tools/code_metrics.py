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

def function_complexities(source: str) -> list[tuple[str, int, int]]:
    """Per-function ``(qualified_name, lineno, complexity)`` for a source string.

    Methods are qualified (``Class.method``); nested defs extend the chain
    (``outer.inner``) and their branches also count toward the enclosing
    function, mirroring how the module-level number aggregates. The symbol
    granularity the idea engine needs: *which* function is the risk, not
    just which file. Unparseable source yields ``[]``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return _function_complexities_tree(tree)


def function_complexities_for_path(path: str | Path) -> list[tuple[str, int, int]]:
    """Path-based :func:`function_complexities`, routed through the shared
    per-build parse cache (``python_structure.parse_cached``) so the file is
    read + parsed once across all analyzers. Byte-identical to calling
    ``function_complexities(path.read_text(...))`` on a parseable file;
    unreadable/unparseable files yield ``[]``."""
    from app.tools.python_structure import parse_cached

    tree = parse_cached(path)
    if tree is None:
        return []
    return _function_complexities_tree(tree)


def _function_complexities_tree(tree: ast.Module) -> list[tuple[str, int, int]]:
    """Core walk shared by the source- and path-based entry points."""
    out: list[tuple[str, int, int]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                complexity = sum(1 for n in ast.walk(child) if isinstance(n, _BRANCH_NODES))
                out.append((name, child.lineno, complexity))
                visit(child, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")

    visit(tree, "")
    return out


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

        # Route the parse through the shared per-build cache (other analyzers
        # parse the same files). ``parse_cached`` returns ``None`` for an
        # unparseable file, exactly the ``SyntaxError`` branch below.
        from app.tools.python_structure import parse_cached

        tree = parse_cached(path)
        if tree is None:
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
