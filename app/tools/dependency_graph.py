from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files
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
        # Per-instance memoization of the three expensive, input-only derivations:
        # the all-files module map, the analyzed structures, and the resolved
        # graph. A single profiling pass calls ``top_central_modules`` +
        # ``edges`` + ``find_cycles`` + ``build`` on ONE builder — that re-ran the
        # full-tree walk and import resolution up to four times for byte-identical
        # output. Caching is keyed only by ``self.root`` (immutable here), so a
        # *new* builder (constructed fresh per dashboard/ideate build) still picks
        # up file changes — the underlying parse cache is mtime-invalidated, and
        # callers never share a builder across a file edit.
        self._module_map_cache: dict[str, str] | None = None
        self._structures_cache: list | None = None
        self._graph_cache: dict[str, DependencyNode] | None = None

    def build(self) -> dict[str, DependencyNode]:
        if self._graph_cache is not None:
            return self._graph_cache

        module_map = self._module_map()
        structures = self._structures()

        graph: dict[str, DependencyNode] = {
            structure.path: DependencyNode(path=structure.path) for structure in structures
        }

        for structure in structures:
            source = structure.path
            for import_name in structure.imports:
                target = self._resolve_internal_import(import_name, module_map, source)
                # ``module_map`` is built from every .py on disk, but the graph's
                # nodes come from the structure analyzer, which can legitimately
                # exclude a file (e.g. one that fails to parse). When an import
                # resolves to such an un-analyzed module it is not a graph node,
                # so skip the edge instead of KeyError-ing on ``graph[target]``.
                if target is None or target == source or target not in graph:
                    continue
                graph[source].imports.add(target)
                graph[target].imported_by.add(source)

        self._graph_cache = graph
        return graph

    def top_central_modules(self, limit: int = 5) -> list[str]:
        graph = self.build()
        ranked = sorted(
            graph.values(),
            key=lambda node: (node.centrality, node.in_degree, node.out_degree, node.path),
            reverse=True,
        )
        return [node.path for node in ranked if node.centrality > 0][:limit]

    def find_cycles(self, limit: int = 10) -> list[list[str]]:
        """Return import cycles (incl. indirect A->B->C->A) via DFS + rec-stack.

        Each cycle is a list of module paths ending back at its start. Results
        are deterministic (graph iterated in sorted order) and de-duplicated by
        rotation so the same cycle isn't reported from multiple entry points.
        """
        graph = self.build()
        adj = {path: sorted(node.imports) for path, node in graph.items()}
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: list[list[str]] = []
        seen_keys: set[frozenset] = set()

        def dfs(node: str, path: list[str]) -> None:
            if len(cycles) >= limit:
                return
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    idx = path.index(neighbor)
                    cycle = path[idx:]
                    key = frozenset(cycle)
                    if len(cycle) >= 2 and key not in seen_keys:
                        seen_keys.add(key)
                        cycles.append(cycle + [neighbor])
            path.pop()
            rec_stack.remove(node)

        for start in sorted(adj):
            if start not in visited:
                dfs(start, [])
        return cycles[:limit]

    def edges(self) -> list[DependencyEdge]:
        module_map = self._module_map()
        structures = self._structures()
        edges: list[DependencyEdge] = []

        for structure in structures:
            for import_name in structure.imports:
                target = self._resolve_internal_import(
                    import_name, module_map, structure.path
                )
                if target is None or target == structure.path:
                    continue
                edges.append(
                    DependencyEdge(source=structure.path, target=target, import_name=import_name)
                )

        dedup: dict[tuple[str, str, str], DependencyEdge] = {}
        for edge in edges:
            dedup[(edge.source, edge.target, edge.import_name)] = edge
        return list(dedup.values())

    def _structures(self) -> list:
        """Analyze the source tree once, memoized per builder instance.

        ``edges`` and ``build`` both consume the same ``ModuleStructure`` list.
        The analyzer's process-level parse cache makes re-parsing cheap, but
        re-walking + re-allocating the structure list is still pure waste within
        one profiling pass — so the list is built at most once here.
        """
        if self._structures_cache is None:
            analyzer = PythonStructureAnalyzer(self.root)
            self._structures_cache = analyzer.analyze()
        return self._structures_cache

    def _module_map(self) -> dict[str, str]:
        if self._module_map_cache is not None:
            return self._module_map_cache
        mapping: dict[str, str] = {}
        for path in iter_source_files(self.root):
            rel = path.relative_to(self.root)
            rel_no_suffix = rel.with_suffix("")
            parts = list(rel_no_suffix.parts)
            if parts[-1] == "__init__":
                module_name = ".".join(parts[:-1])
            else:
                module_name = ".".join(parts)
            if module_name:
                mapping[module_name] = str(rel)
        self._module_map_cache = mapping
        return mapping

    def _resolve_internal_import(
        self,
        import_name: str,
        module_map: dict[str, str],
        source_path: str | None = None,
    ) -> str | None:
        # Relative imports carry a leading-dot prefix (one dot per ``node.level``)
        # emitted by ``python_structure._import_names``. They are path-DEPENDENT:
        # the same ``.b`` means a different module from each importing file, so
        # they must be anchored to ``source_path``'s package BEFORE resolution.
        # Absolute imports (no leading dot) fall straight through to the frozen
        # pop-to-package walk below, byte-identical to today.
        if import_name.startswith("."):
            import_name = self._absolutize_relative(import_name, source_path)
            if import_name is None:
                # Level escaped the project root (or no source context): there is
                # no internal module to point at, so DON'T fabricate an edge.
                return None

        if import_name in module_map:
            return module_map[import_name]

        parts = import_name.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in module_map:
                return module_map[candidate]
            parts.pop()
        return None

    @staticmethod
    def _absolutize_relative(import_name: str, source_path: str | None) -> str | None:
        """Turn a leading-dot relative candidate into an absolute dotted module.

        ``import_name`` is ``"." * level + tail`` (``tail`` possibly empty, e.g.
        ``"."`` for ``from . import *``). It is resolved against the importing
        file's PACKAGE — the file's dotted path with its final component dropped
        (``proj/sub/c.py`` -> package ``proj.sub``). ``level`` dots pop that many
        components off the package; a ``tail`` (``b`` / ``b.fb``) is then appended.

        Returns the absolute dotted module, or ``None`` when there is no source
        context or the level pops ABOVE the project root (an import that escapes
        the analyzed tree has no internal target — we must not invent one).
        Deterministic: pure string arithmetic, no I/O, no clock/random.
        """
        if not source_path:
            return None
        level = len(import_name) - len(import_name.lstrip("."))
        tail = import_name[level:]

        # Package of the importing file = its dotted path minus the file name.
        # ``__init__.py`` IS its package, so it is its own anchor (drop only the
        # ``__init__`` leaf); a normal module drops its own leaf too.
        rel = Path(source_path).with_suffix("")
        pkg_parts = list(rel.parts)
        if pkg_parts and pkg_parts[-1] == "__init__":
            pkg_parts.pop()
        # A normal module ``proj/sub/c.py`` lives IN package ``proj.sub``: drop
        # the module's own name to get its package.
        elif pkg_parts:
            pkg_parts.pop()

        # ``level`` dots: level 1 == "current package" (no further pop); each
        # extra dot pops one more package component.
        pops = level - 1
        if pops > len(pkg_parts):
            # Escapes the project root — no internal module exists for it.
            return None
        base = pkg_parts[: len(pkg_parts) - pops] if pops else pkg_parts

        absolute_parts = base + (tail.split(".") if tail else [])
        return ".".join(absolute_parts)
