from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FileContext:
    target_file: str
    code_window: str
    imports: list[str] = field(default_factory=list)
    related_tests: list[str] = field(default_factory=list)
    surrounding_symbols: list[str] = field(default_factory=list)


@dataclass
class ContextExtractionResult:
    contexts: list[FileContext] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"contexts": [asdict(context) for context in self.contexts]}


class ContextExtractor:
    """Extract compact code windows around semantic patch targets."""

    def extract(
        self,
        project_root: str | Path,
        target_files: list[str],
        window_lines: int = 40,
    ) -> ContextExtractionResult:
        root = Path(project_root).resolve()
        contexts: list[FileContext] = []

        for rel_path in target_files[:3]:
            target = (root / rel_path).resolve()
            if not str(target).startswith(str(root)) or not target.exists():
                continue

            try:
                source = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            lines = source.splitlines()
            window = "\n".join(lines[:window_lines])

            symbols: list[str] = []
            imports: list[str] = []
            try:
                tree = ast.parse(source)
            except SyntaxError:
                tree = None

            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(f"import {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        names = ", ".join(alias.name for alias in node.names)
                        imports.append(f"from {module} import {names}")
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        symbols.append(node.name)

            related_tests: list[str] = []
            test_dir = root / "tests"
            if test_dir.exists():
                stem = Path(rel_path).stem
                for test_file in test_dir.rglob("*.py"):
                    if stem in test_file.name:
                        related_tests.append(str(test_file.relative_to(root).as_posix()))

            contexts.append(
                FileContext(
                    target_file=rel_path,
                    code_window=window,
                    imports=imports,
                    related_tests=related_tests,
                    surrounding_symbols=symbols,
                )
            )

        return ContextExtractionResult(contexts=contexts)
