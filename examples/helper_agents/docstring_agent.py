from __future__ import annotations

"""
DocstringAgent — Detects missing docstrings and generates patches.

Scans Python files for:
- Functions without docstrings
- Classes without docstrings
- Generates semantic patches to add them
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DocstringGap:
    file: str
    line: int
    symbol_type: str  # function | class
    name: str
    suggestion: str


@dataclass
class DocstringReport:
    gaps: list[DocstringGap] = field(default_factory=list)
    patched_files: list[str] = field(default_factory=list)
    total_symbols: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_symbols": self.total_symbols,
            "gaps_found": len(self.gaps),
            "patched_files": self.patched_files,
            "gaps": [
                {
                    "file": g.file,
                    "line": g.line,
                    "symbol_type": g.symbol_type,
                    "name": g.name,
                    "suggestion": g.suggestion,
                }
                for g in self.gaps
            ],
        }


class DocstringAgent:
    """Helper agent: finds and fixes missing docstrings."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.report = DocstringReport()

    def scan(self, target_files: list[str] | None = None) -> DocstringReport:
        files = self._discover_files(target_files)

        for rel_path in files:
            full = self.root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            self._scan_file(rel_path, source)

        return self.report

    def patch(self, target_files: list[str] | None = None) -> list[str]:
        """Generate patches for missing docstrings. Returns list of patched files."""
        files = self._discover_files(target_files)
        patched: list[str] = []

        for rel_path in files:
            full = self.root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            new_source = self._patch_file(rel_path, source)
            if new_source != source:
                full.write_text(new_source, encoding="utf-8")
                patched.append(rel_path)

        self.report.patched_files = patched
        return patched

    def _discover_files(self, target_files: list[str] | None = None) -> list[str]:
        if target_files:
            return target_files
        return [
            str(p.relative_to(self.root).as_posix())
            for p in self.root.rglob("*.py")
            if ".apex" not in p.parts and "__pycache__" not in p.parts
        ]

    def _scan_file(self, rel_path: str, source: str) -> None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.report.total_symbols += 1
                if ast.get_docstring(node) is None:
                    self.report.gaps.append(
                        DocstringGap(
                            file=rel_path,
                            line=node.lineno,
                            symbol_type="function",
                            name=node.name,
                            suggestion=f'Add docstring to function "{node.name}"',
                        )
                    )
            elif isinstance(node, ast.ClassDef):
                self.report.total_symbols += 1
                if ast.get_docstring(node) is None:
                    self.report.gaps.append(
                        DocstringGap(
                            file=rel_path,
                            line=node.lineno,
                            symbol_type="class",
                            name=node.name,
                            suggestion=f'Add docstring to class "{node.name}"',
                        )
                    )

    def _patch_file(self, rel_path: str, source: str) -> str:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        lines = source.splitlines(keepends=True)
        modified = False

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if ast.get_docstring(node) is None:
                    indent = self._get_indent(lines[node.lineno - 1])
                    body_indent = indent + "    "
                    docstring = f'{body_indent}"""{node.name} implementation."""\n'
                    insert_at = node.lineno
                    if insert_at < len(lines) and lines[insert_at].strip().startswith('"""'):
                        continue
                    lines.insert(insert_at, docstring)
                    modified = True

        return "".join(lines) if modified else source

    def _get_indent(self, line: str) -> str:
        stripped = line.lstrip()
        if stripped:
            return line[: line.index(stripped)]
        return line


# Plugin registration
__plugin_name__ = "docstring_agent"

def register(proxy):
    agent = DocstringAgent(proxy.get("project_root", "."))
    proxy.add_hook("before_scan", lambda ctx: agent.scan())
    proxy.add_hook("after_scan", lambda ctx: agent.patch())
