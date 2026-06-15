from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files


@dataclass
class ModuleStructure:
    path: str
    imports: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)


def _is_type_checking_test(test: ast.expr) -> bool:
    """True if an ``if`` test is ``TYPE_CHECKING`` (bare or ``typing.TYPE_CHECKING``).

    Imports guarded by such a block never execute at runtime, so they are
    type-only and must not be counted as real import edges.
    """
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


class PythonStructureAnalyzer:
    def __init__(self, root: str | Path, max_files: int = 500) -> None:
        self.root = Path(root)
        self.max_files = max_files

    def analyze(self) -> list[ModuleStructure]:
        if not self.root.exists():
            return []

        results: list[ModuleStructure] = []
        scanned = 0
        # iter_source_files is sorted AND prunes excluded/worktree dirs, so the
        # max_files cap below is applied AFTER filtering: deterministic across
        # machines (CI vs local), kept in sync with the all-files module map, and
        # never filled with .claude worktree copies (which sort first and would
        # otherwise crowd out every real module before the cap is reached).
        for path in iter_source_files(self.root):
            if scanned >= self.max_files:
                break
            scanned += 1
            structure = self._analyze_file(path)
            if structure is not None:
                results.append(structure)
        return results

    def _analyze_file(self, path: Path) -> ModuleStructure | None:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (SyntaxError, OSError, ValueError):
            return None

        imports: list[str] = []
        symbols: list[str] = []

        # Imports under `if TYPE_CHECKING:` are type-only — they never run, so they
        # are NOT real import edges. Counting them lets a type-hint import that was
        # added to BREAK a cycle get miscounted AS a cycle (a false positive that
        # cost real grade points). Collect those nodes and skip them below. The
        # `else` arm of such a block DOES run, so only its `body` is excluded.
        type_only: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and _is_type_checking_test(node.test):
                for stmt in node.body:
                    for inner in ast.walk(stmt):
                        if isinstance(inner, (ast.Import, ast.ImportFrom)):
                            type_only.add(id(inner))

        for node in ast.walk(tree):
            if id(node) in type_only:
                continue
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
