from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.tools.python_structure import PythonStructureAnalyzer


@dataclass
class DependencyEdge:
    source: str
    target: str
    import_name: str


@dataclass
class DependencyNode:
    path: str
    imports: set[str] = field(default_factory=set)
    imported_by: set[str] = field(default_factory=set)

    @property
    def out_degree(self) -> int:
        return len(self.imports)

    @property
    def in_degree(self) -> int:
        return len(self.imported_by)

    @property
    def centrality(self) -> int:
        return self.in_degree + self.out_degree


class DependencyGraphBuilder:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def build(self) -> dict[str, DependencyNode]:
        module_map = self._module_map()
        analyzer = PythonStructureAnalyzer(self.root)
        structures = analyzer.analyze()

        graph: dict[str, DependencyNode] = {
            structure.path: DependencyNode(path=structure.path) for structure in structures
        }

        for structure in structures:
            source = structure.path
            for import_name in structure.imports:
                target = self._resolve_internal_import(import_name, module_map)
                if target is None or target == source:
                    continue
                graph[source].imports.add(target)
                graph[target].imported_by.add(source)

        return graph

    def top_central_modules(self, limit: int = 5) -> list[str]:
        graph = self.build()
        ranked = sorted(
            graph.values(),
            key=lambda node: (node.centrality, node.in_degree, node.out_degree, node.path),
            reverse=True,
        )
        return [node.path for node in ranked if node.centrality > 0][:limit]

    def edges(self) -> list[DependencyEdge]:
        module_map = self._module_map()
        analyzer = PythonStructureAnalyzer(self.root)
        structures = analyzer.analyze()
        edges: list[DependencyEdge] = []

        for structure in structures:
            for import_name in structure.imports:
                target = self._resolve_internal_import(import_name, module_map)
                if target is None or target == structure.path:
                    continue
                edges.append(
                    DependencyEdge(source=structure.path, target=target, import_name=import_name)
                )

        dedup: dict[tuple[str, str, str], DependencyEdge] = {}
        for edge in edges:
            dedup[(edge.source, edge.target, edge.import_name)] = edge
        return list(dedup.values())

    def _module_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for path in self.root.rglob("*.py"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            rel_no_suffix = rel.with_suffix("")
            parts = list(rel_no_suffix.parts)
            if parts[-1] == "__init__":
                module_name = ".".join(parts[:-1])
            else:
                module_name = ".".join(parts)
            if module_name:
                mapping[module_name] = str(rel)
        return mapping

    def _resolve_internal_import(self, import_name: str, module_map: dict[str, str]) -> str | None:
        if import_name in module_map:
            return module_map[import_name]

        parts = import_name.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in module_map:
                return module_map[candidate]
            parts.pop()
        return None
