from __future__ import annotations

"""
DependencyAgent — Analyzes cross-file import graphs.

Builds:
- Module dependency graph
- Detects circular imports
- Finds orphaned modules (no imports, not imported)
- Identifies high-centrality modules
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ImportEdge:
    source: str
    target: str
    import_type: str  # import | from
    symbols: list[str] = field(default_factory=list)


@dataclass
class DependencyReport:
    edges: list[ImportEdge] = field(default_factory=list)
    circular_imports: list[list[str]] = field(default_factory=list)
    orphaned_modules: list[str] = field(default_factory=list)
    high_centrality: list[tuple[str, int]] = field(default_factory=list)
    total_modules: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_modules": self.total_modules,
            "total_edges": len(self.edges),
            "circular_imports": self.circular_imports,
            "orphaned_modules": self.orphaned_modules,
            "high_centrality": [{"module": m, "connections": c} for m, c in self.high_centrality],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "import_type": e.import_type,
                    "symbols": e.symbols,
                }
                for e in self.edges
            ],
        }


class DependencyAgent:
    """Helper agent: analyzes import graphs and detects architectural issues."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.report = DependencyReport()

    def analyze(self, target_files: list[str] | None = None) -> DependencyReport:
        files = self._discover_files(target_files)
        self.report.total_modules = len(files)

        for rel_path in files:
            full = self.root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            self._scan_imports(rel_path, source)

        self._detect_circular_imports()
        self._find_orphaned_modules(files)
        self._calculate_centrality(files)

        return self.report

    def _discover_files(self, target_files: list[str] | None = None) -> list[str]:
        if target_files:
            return target_files
        return [
            str(p.relative_to(self.root).as_posix())
            for p in self.root.rglob("*.py")
            if ".apex" not in p.parts and "__pycache__" not in p.parts
        ]

    def _scan_imports(self, rel_path: str, source: str) -> None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.report.edges.append(
                        ImportEdge(
                            source=rel_path,
                            target=alias.name,
                            import_type="import",
                            symbols=[alias.name],
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                symbols = [alias.name for alias in node.names]
                self.report.edges.append(
                    ImportEdge(
                        source=rel_path,
                        target=module,
                        import_type="from",
                        symbols=symbols,
                    )
                )

    def _detect_circular_imports(self) -> None:
        def _to_path(module_name: str) -> str:
            """Convert module dot-path to file path (e.g. app.b -> app/b.py)."""
            return module_name.replace(".", "/") + ".py"

        graph: dict[str, set[str]] = {}
        for edge in self.report.edges:
            if edge.source not in graph:
                graph[edge.source] = set()
            # Map module name to file path if it looks like a module import
            target = edge.target
            if "." in target and not target.endswith(".py"):
                target = _to_path(target)
            graph[edge.source].add(target)

        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: list[list[str]] = []

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)

            path.pop()
            rec_stack.remove(node)

        for node in graph:
            if node not in visited:
                dfs(node, [])

        self.report.circular_imports = cycles

    def _find_orphaned_modules(self, files: list[str]) -> None:
        imported = set(edge.target for edge in self.report.edges)
        importers = set(edge.source for edge in self.report.edges)

        orphaned = []
        for f in files:
            if f not in importers and f not in imported:
                orphaned.append(f)

        self.report.orphaned_modules = orphaned

    def _calculate_centrality(self, files: list[str]) -> None:
        connections: dict[str, int] = {f: 0 for f in files}
        for edge in self.report.edges:
            if edge.source in connections:
                connections[edge.source] += 1
            if edge.target in connections:
                connections[edge.target] += 1

        sorted_modules = sorted(connections.items(), key=lambda x: x[1], reverse=True)
        self.report.high_centrality = [(m, c) for m, c in sorted_modules[:5] if c > 0]


# Plugin registration
__plugin_name__ = "dependency_agent"

def register(proxy):
    agent = DependencyAgent(proxy.get("project_root", "."))
    proxy.add_hook("before_scan", lambda ctx: agent.analyze())
