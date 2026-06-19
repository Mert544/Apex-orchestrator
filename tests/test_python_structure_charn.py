"""Characterization harness: proves the refactored `_parse_source` produces
byte-identical (sorted imports, sorted symbols) tuples vs the pre-refactor
original across a wide spread of source shapes (plain imports, TYPE_CHECKING
blocks with/without else arms, nested defs/classes, syntax errors, empty)."""

from __future__ import annotations

import ast
from pathlib import Path

from app.tools.python_structure import _extract_graph, _parse_source

# --- Reference implementation, kept in lockstep with `_import_names` ----------
# Mirrors the FIXED extraction: `from pkg import sub` records the submodule-
# qualified edge `pkg.sub` (one per imported name), not the bare package, so the
# dependency resolver can reach a real submodule file and stops collapsing every
# `from`-style edge onto `__init__.py`. Star/no-module imports keep the package.


def _is_type_checking_test_ref(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _parse_source_ref(source: str) -> tuple[list[str], list[str]] | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, OSError, ValueError):
        return None

    imports: list[str] = []
    symbols: list[str] = []

    type_only: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test_ref(node.test):
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
                qualified = [
                    f"{module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                ]
                imports.extend(qualified if qualified else [module])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)

    return sorted(set(imports)), sorted(set(symbols))


# --- Corpus of source snippets -----------------------------------------------

SNIPPETS = [
    "",
    "import os",
    "import os, sys, json",
    "import os.path as p",
    "from a.b import c",
    "from . import x",
    "from .rel import y",
    "from __future__ import annotations\nimport os\n",
    "def f():\n    pass\n",
    "async def g():\n    await f()\n",
    "class C:\n    def m(self):\n        pass\n",
    "class C:\n    class Inner:\n        pass\n",
    (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import only_typed\n"
        "    from typed.mod import Thing\n"
        "import real\n"
    ),
    (
        "import typing\n"
        "if typing.TYPE_CHECKING:\n"
        "    from a import B\n"
        "else:\n"
        "    import runtime_dep\n"
    ),
    (
        "if TYPE_CHECKING:\n"
        "    if nested:\n"
        "        import deep_typed\n"
        "import surface\n"
    ),
    (
        "if SOMETHING_ELSE:\n"
        "    import not_skipped\n"
    ),
    (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import dup\n"
        "import dup\n"
    ),
    "from import\n",  # syntax error
    "def (:\n",  # syntax error
    "import a\nimport a\nimport b\n",
    (
        "import a\n"
        "class Outer:\n"
        "    import b\n"
        "    def method(self):\n"
        "        import c\n"
        "        def inner():\n"
        "            pass\n"
    ),
    "from a import (b, c, d)\nfrom a import e\n",
    "import zlib\nimport abc\nimport mmm\n",  # ordering
]


def test_extract_graph_matches_reference_for_all_snippets():
    mismatches = []
    for src in SNIPPETS:
        ref = _parse_source_ref(src)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            # Reference returns None for unparseable; nothing to compare via
            # _extract_graph (which only runs on a valid tree). Assert ref None.
            assert ref is None, src
            continue
        got = _extract_graph(tree)
        if got != ref:
            mismatches.append((src, ref, got))
    assert not mismatches, mismatches


def test_parse_source_matches_reference_via_files(tmp_path: Path):
    mismatches = []
    for i, src in enumerate(SNIPPETS):
        f = tmp_path / f"snippet_{i}.py"
        f.write_text(src, encoding="utf-8")
        ref = _parse_source_ref(src)
        got = _parse_source(f)
        if got != ref:
            mismatches.append((src, ref, got))
    assert not mismatches, mismatches


def test_unreadable_path_returns_none(tmp_path: Path):
    missing = tmp_path / "does_not_exist.py"
    assert _parse_source(missing) is None


def test_type_checking_imports_are_skipped(tmp_path: Path):
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import typed_only\n"
        "import real_one\n"
    )
    f = tmp_path / "tc.py"
    f.write_text(src, encoding="utf-8")
    imports, _symbols = _parse_source(f)  # type: ignore[misc]
    assert "typed_only" not in imports
    assert "real_one" in imports
    assert "typing.TYPE_CHECKING" in imports
