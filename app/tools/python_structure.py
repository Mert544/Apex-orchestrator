from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModuleStructure:
    path: str
    imports: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)


class PythonStructureAnalyzer:
    def __init__(self, root: str | Path, max_files: int = 500) -> None:
        self.root = Path(root)
        self.max_files = max_files

    def analyze(self) -> list[ModuleStructure]:
        if not self.root.exists():
            return []

        results: list[ModuleStructure] = []
        scanned = 0
        # Sort before applying max_files: rglob order is filesystem-dependent, so
        # an unsorted cap would analyze a *different* 500 files on different
        # machines (CI vs local) — non-deterministic, and it desynced this view
        # from the all-files module map (a KeyError in the dependency graph).
        for path in sorted(self.root.rglob("*.py")):
            if scanned >= self.max_files:
                break
            if not path.is_file():
                continue
            scanned += 1
            structure = self._analyze_file(path)
            if structure is not None:
                results.append(structure)
        return results

    def _analyze_file(self, path: Path) -> ModuleStructure | None:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except Exception:
            return None

        imports: list[str] = []
        symbols: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module:
                    imports.append(module)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)

        rel = str(path.relative_to(self.root))
        return ModuleStructure(path=rel, imports=sorted(set(imports)), symbols=sorted(set(symbols)))
