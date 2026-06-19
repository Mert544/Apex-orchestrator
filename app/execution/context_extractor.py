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


def _read_source(target: Path, root: Path) -> str | None:
    if not str(target).startswith(str(root)) or not target.exists():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _parse_tree(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None


def _format_import(node: ast.Import) -> list[str]:
    return [f"import {alias.name}" for alias in node.names]


def _format_import_from(node: ast.ImportFrom) -> str:
    module = node.module or ""
    names = ", ".join(alias.name for alias in node.names)
    return f"from {module} import {names}"


def _collect_imports_and_symbols(source: str) -> tuple[list[str], list[str]]:
    imports: list[str] = []
    symbols: list[str] = []
    tree = _parse_tree(source)
    if tree is None:
        return imports, symbols
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(_format_import(node))
        elif isinstance(node, ast.ImportFrom):
            imports.append(_format_import_from(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
    return imports, symbols


def _find_related_tests(root: Path, rel_path: str) -> list[str]:
    test_dir = root / "tests"
    if not test_dir.exists():
        return []
    stem = Path(rel_path).stem
    return [
        str(test_file.relative_to(root).as_posix())
        for test_file in test_dir.rglob("*.py")
        if stem in test_file.name
    ]


def _build_file_context(root: Path, rel_path: str, window_lines: int) -> FileContext | None:
    target = (root / rel_path).resolve()
    source = _read_source(target, root)
    if source is None:
        return None
    window = "\n".join(source.splitlines()[:window_lines])
    imports, symbols = _collect_imports_and_symbols(source)
    return FileContext(
        target_file=rel_path,
        code_window=window,
        imports=imports,
        related_tests=_find_related_tests(root, rel_path),
        surrounding_symbols=symbols,
    )


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
            context = _build_file_context(root, rel_path, window_lines)
            if context is not None:
                contexts.append(context)
        return ContextExtractionResult(contexts=contexts)
