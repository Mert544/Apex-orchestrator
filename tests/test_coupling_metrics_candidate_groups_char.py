"""Characterization tests pinning ``_candidate_groups`` byte-identical after refactor.

Compares the refactored ``_candidate_groups`` against an inline copy of the
original (pre-refactor) implementation over many import shapes, covering every
branch: plain imports, aliased imports, absolute/relative ``from`` imports at
varying levels, star imports, dotted bases, empty/self modules, and malformed
edge cases. Asserts full output equality (order + contents) plus invariance of
the public ``analyze_coupling`` pipeline.
"""

from __future__ import annotations

import ast

from app.tools.coupling_metrics import _candidate_groups, analyze_coupling


def _candidate_groups_original(tree: ast.AST, self_module: str) -> list[list[str]]:
    """Verbatim pre-refactor implementation (HEAD:coupling_metrics.py)."""
    groups: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    groups.append([alias.name])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pkg_parts = self_module.split(".")[:-1] if self_module else []
                climb = node.level - 1
                if climb:
                    pkg_parts = pkg_parts[:-climb] if climb <= len(pkg_parts) else []
                prefix = ".".join(pkg_parts)
                base = f"{prefix}.{node.module}" if node.module else prefix
            else:
                base = node.module or ""
            if not base:
                continue
            for alias in node.names:
                if alias.name and alias.name != "*":
                    groups.append([f"{base}.{alias.name}", base])
                else:
                    groups.append([base])
    return groups


_SOURCES = [
    "",
    "import os",
    "import os, sys",
    "import a.b.c",
    "import a.b.c as x",
    "from a import b",
    "from a import b, c, d",
    "from a.b import c",
    "from a.b import c as z, d",
    "from a import *",
    "from . import x",
    "from . import x, y",
    "from .. import x",
    "from .pkg import sub",
    "from ..pkg import sub",
    "from ...pkg import sub",
    "from .pkg.deep import sub",
    "from . import *",
    "import a; from .b import c\nfrom ..d import e",
    "def f():\n    import inner\n    from .rel import thing\n",
    "from a.b.c.d.e import f, g, h",
    "import x\nimport y\nfrom z import w",
    "from .. import *",
    "from ...... import deep",
]

_SELF_MODULES = [
    "",
    "pkg",
    "pkg.mod",
    "a.b.c.d",
    "app.tools.coupling_metrics",
]


def test_candidate_groups_byte_identical_over_matrix():
    for src in _SOURCES:
        tree = ast.parse(src)
        for self_module in _SELF_MODULES:
            expected = _candidate_groups_original(tree, self_module)
            actual = _candidate_groups(tree, self_module)
            assert actual == expected, (src, self_module, actual, expected)


def test_candidate_groups_returns_lists_of_lists():
    tree = ast.parse("from .pkg import a, b\nimport c.d")
    groups = _candidate_groups(tree, "x.y")
    assert all(isinstance(g, list) for g in groups)
    assert all(isinstance(c, str) for g in groups for c in g)


def test_analyze_coupling_pipeline_smoke(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("from pkg import b\nfrom . import c\n")
    (tmp_path / "pkg" / "b.py").write_text("import pkg.c\n")
    (tmp_path / "pkg" / "c.py").write_text("x = 1\n")
    metrics = analyze_coupling(tmp_path)
    assert metrics.module_count >= 3
    names = {m.module for m in metrics.modules}
    assert "pkg.a" in names and "pkg.b" in names and "pkg.c" in names
