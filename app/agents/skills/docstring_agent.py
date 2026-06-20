from __future__ import annotations

"""DocstringAgent — Detects missing docstrings and generates patches."""

import ast
from pathlib import Path
from typing import Any

from app.agents.base import Agent
from app.engine.skip_dirs import iter_source_files
from app.execution.semantic.transforms.docstring import _body_insertion


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
            for p in iter_source_files(root)
        ]

    def _scan_file(self, rel_path: str, source: str) -> tuple[list[dict[str, Any]], int]:
        gaps: list[dict[str, Any]] = []
        total = 0
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, MemoryError):
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
        """Insert ``"{name} implementation."`` as each undocumented symbol's first
        body statement, returning the patched source (or ``source`` unchanged).

        Insertion points are computed by the body-accurate transform helper
        :func:`app.execution.semantic.transforms.docstring._body_insertion`, which
        derives the position from the AST's first body statement. That handles
        multi-line signatures, decorators, nested defs, and blank-line gaps —
        cases the old ``node.lineno + 1`` heuristic mishandled (it landed a
        detached module-level string that the CLI soundness gate then rolled
        back, so those functions never got a docstring). The agent's public
        contract is preserved: the doc text stays ``"{name} implementation."`` and
        single-line signatures land byte-identically to before. The result is
        re-parsed; an edit that would not parse is discarded (the file is left
        unchanged) so this never emits broken Python.
        """
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, MemoryError):
            return source

        lines = source.splitlines(keepends=True)
        # Collect (insert_index, docstring_line) placements, skipping any node
        # whose body already opens with a string literal (idempotent) or whose
        # body offers no insertion point.
        placements: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ) or ast.get_docstring(node) is not None:
                continue
            spot = _body_insertion(node, lines)
            if spot is None:
                continue
            insert_at, body_indent = spot
            if lines[insert_at].strip().startswith(('"""', "'''", 'r"""', "r'''")):
                continue
            doc = f'{body_indent}"""{node.name} implementation."""\n'
            placements.append((insert_at, doc))

        if not placements:
            return source

        # Splice from the bottom up so earlier indices stay valid across inserts.
        new_lines = list(lines)
        for insert_at, doc in sorted(placements, key=lambda p: p[0], reverse=True):
            new_lines.insert(insert_at, doc)
        patched = "".join(new_lines)

        # Self-validating: never hand back unparseable Python.
        try:
            ast.parse(patched)
        except (SyntaxError, RecursionError, MemoryError):
            return source
        return patched
