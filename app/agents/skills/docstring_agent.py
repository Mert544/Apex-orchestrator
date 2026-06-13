from __future__ import annotations

"""DocstringAgent — Detects missing docstrings and generates patches."""

import ast
from pathlib import Path
from typing import Any

from app.agents.base import Agent


class DocstringAgent(Agent):
    """Agent: finds and fixes missing docstrings."""

    def __init__(self, name: str = "docstring", **kwargs: Any) -> None:
        super().__init__(name=name, role="documentation_enforcer", **kwargs)
        self.project_root: Path | None = None

    def _execute(self, project_root: str | Path = ".", patch: bool = False, **kwargs: Any) -> dict[str, Any]:
        root = Path(project_root).resolve()
        self.project_root = root

        gaps: list[dict[str, Any]] = []
        patched_files: list[str] = []
        total_symbols = 0

        files = self._discover_files(root)
        for rel_path in files:
            full = root / rel_path
            try:
                source = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            file_gaps, file_total = self._scan_file(rel_path, source)
            gaps.extend(file_gaps)
            total_symbols += file_total

            if patch and file_gaps:
                new_source = self._patch_file(rel_path, source)
                if new_source != source:
                    full.write_text(new_source, encoding="utf-8")
                    patched_files.append(rel_path)

        if gaps:
            self.send(
                topic="docstring.gaps.found",
                payload={"count": len(gaps), "files": list({g["file"] for g in gaps})},
            )

        return {
            "agent": self.name,
            "role": self.role,
            "total_symbols": total_symbols,
            "gaps_found": len(gaps),
            "patched_files": patched_files,
            "gaps": gaps,
        }

    def _discover_files(self, root: Path) -> list[str]:
        return [
            str(p.relative_to(root).as_posix())
            for p in root.rglob("*.py")
            if ".apex" not in p.parts and "__pycache__" not in p.parts
        ]

    def _scan_file(self, rel_path: str, source: str) -> tuple[list[dict[str, Any]], int]:
        gaps: list[dict[str, Any]] = []
        total = 0
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return gaps, total

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                if ast.get_docstring(node) is None:
                    gaps.append(
                        {
                            "file": rel_path,
                            "line": node.lineno,
                            "symbol_type": "function",
                            "name": node.name,
                        }
                    )
            elif isinstance(node, ast.ClassDef):
                total += 1
                if ast.get_docstring(node) is None:
                    gaps.append(
                        {
                            "file": rel_path,
                            "line": node.lineno,
                            "symbol_type": "class",
                            "name": node.name,
                        }
                    )
        return gaps, total

    def _patch_file(self, rel_path: str, source: str) -> str:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        lines = source.splitlines(keepends=True)
        modified = False

        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))) and (ast.get_docstring(node) is None):
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
        return line[: line.index(stripped)] if stripped else line
