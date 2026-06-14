from __future__ import annotations

"""DependencyAgent — Analyzes cross-file import graphs."""

import ast
from pathlib import Path
from typing import Any

from app.agents.base import Agent
from app.engine.skip_dirs import iter_source_files


class DependencyAgent(Agent):
    """Agent: analyzes import graphs and detects architectural issues."""

    def __init__(self, name: str = "dependency", **kwargs: Any) -> None:
        super().__init__(name=name, role="architecture_analyst", **kwargs)
        self.project_root: Path | None = None

    def _execute(self, project_root: str | Path = ".", **kwargs: Any) -> dict[str, Any]:
        root = Path(project_root).resolve()
        self.project_root = root

        edges: list[dict[str, Any]] = []
        files = self._discover_files(root)

        for rel_path in files:
            full = root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            edges.extend(self._scan_imports(rel_path, source))

        circular = self._detect_circular(edges, files)
        orphaned = self._find_orphaned(files, edges)
        centrality = self._calculate_centrality(files, edges)

        self.send(
            topic="dependency.graph.complete",
            payload={"modules": len(files), "edges": len(edges), "circular": len(circular)},
        )

        return {
            "agent": self.name,
            "role": self.role,
            "total_modules": len(files),
            "total_edges": len(edges),
            "circular_imports": circular,
            "orphaned_modules": orphaned,
            "high_centrality": centrality,
            "edges": edges,
        }

    def _discover_files(self, root: Path) -> list[str]:
        return [
            str(p.relative_to(root).as_posix())
            for p in iter_source_files(root)
        ]

    def _scan_imports(self, rel_path: str, source: str) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return edges

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append(
                        {
                            "source": rel_path,
                            "target": alias.name,
                            "import_type": "import",
                            "symbols": [alias.name],
                        }
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                edges.append(
                    {
                        "source": rel_path,
                        "target": module,
                        "import_type": "from",
                        "symbols": [a.name for a in node.names],
                    }
                )
        return edges

    def _detect_circular(self, edges: list[dict[str, Any]], files: list[str]) -> list[list[str]]:
        def to_path(module: str) -> str:
            return module.replace(".", "/") + ".py"

        graph: dict[str, set[str]] = {f: set() for f in files}
        for edge in edges:
            src = edge["source"]
            tgt = edge["target"]
            if "." in tgt and not tgt.endswith(".py"):
                tgt = to_path(tgt)
            if src in graph:
                graph[src].add(tgt)

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
                    idx = path.index(neighbor)
                    cycle = path[idx:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)
            path.pop()
            rec_stack.remove(node)

        for node in graph:
            if node not in visited:
                dfs(node, [])
        return cycles

    def _find_orphaned(self, files: list[str], edges: list[dict[str, Any]]) -> list[str]:
        imported = {e["target"] for e in edges}
        importers = {e["source"] for e in edges}
        return [f for f in files if f not in importers and f not in imported]

    def _calculate_centrality(self, files: list[str], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        connections: dict[str, int] = {f: 0 for f in files}
        for edge in edges:
            if edge["source"] in connections:
                connections[edge["source"]] += 1
            if edge["target"] in connections:
                connections[edge["target"]] += 1
        sorted_modules = sorted(connections.items(), key=lambda x: x[1], reverse=True)
        return [{"module": m, "connections": c} for m, c in sorted_modules[:5] if c > 0]
