"""Regression: RELATIVE imports must resolve to their ABSOLUTE target.

A confirmed correctness defect in ``python_structure._import_names`` dropped
``node.level`` for relative imports, so the dependency graph carried both
false-negative and false-positive edges (hiding OR fabricating cycles):

* ``from . import b`` (level=1, no module) emitted ``[]`` — the real sibling
  edge was SILENTLY DROPPED (false negative).
* ``from .b import x`` (level=1) emitted ``b.x``, dropping the level — the
  resolver then popped to a TOP-LEVEL ``b``, recording ``proj/sub/c.py`` as
  importing top-level ``b.py`` instead of ``proj/sub/b.py`` (phantom edge).

The fix preserves ``node.level`` as a leading-dot prefix and absolutizes it in
``dependency_graph._resolve_internal_import`` against the importing file's
package. These tests pin the fixed behavior; absolute-import resolution is
covered (and frozen) by ``test_import_from_submodule_resolution_eyml.py``.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.dependency_graph import DependencyGraphBuilder


def _edges(root: Path) -> list[tuple[str, str]]:
    return sorted((e.source, e.target) for e in DependencyGraphBuilder(root).edges())


def _make_proj(root: Path) -> Path:
    """Create ``proj/sub`` package skeleton and return the ``sub`` dir."""
    sub = root / "proj" / "sub"
    sub.mkdir(parents=True)
    (root / "proj" / "__init__.py").write_text("")
    (sub / "__init__.py").write_text("")
    return sub


def test_from_dot_import_sibling_edge_is_not_dropped(tmp_path):
    """``from . import b`` resolves to the SAME-package sibling ``b.py`` (the
    edge the old code silently dropped)."""
    sub = _make_proj(tmp_path)
    (sub / "b.py").write_text("x = 1\n")
    (sub / "d.py").write_text("from . import b\n")
    edges = _edges(tmp_path)
    assert ("proj/sub/d.py", "proj/sub/b.py") in edges


def test_from_dot_module_import_resolves_to_same_package_not_top_level(tmp_path):
    """Auditor's phantom case: ``from .b import fb`` in ``proj/sub/c.py`` must
    resolve to ``proj/sub/b.py``, NOT to a top-level ``b.py`` — even when a
    same-named top-level ``b.py`` exists to tempt the resolver."""
    sub = _make_proj(tmp_path)
    (sub / "b.py").write_text("fb = 1\n")
    (sub / "c.py").write_text("from .b import fb\n")
    # A decoy top-level module the buggy resolver mis-popped to.
    (tmp_path / "b.py").write_text("tb = 1\n")
    edges = _edges(tmp_path)
    assert ("proj/sub/c.py", "proj/sub/b.py") in edges
    assert ("proj/sub/c.py", "b.py") not in edges


def test_two_level_relative_import_resolves_up_two_packages(tmp_path):
    """``from ..pkg import y`` in ``proj/sub/c.py`` resolves up two levels to
    ``proj/pkg.py``."""
    sub = _make_proj(tmp_path)
    (tmp_path / "proj" / "pkg.py").write_text("y = 1\n")
    (sub / "c.py").write_text("from ..pkg import y\n")
    edges = _edges(tmp_path)
    assert ("proj/sub/c.py", "proj/pkg.py") in edges


def test_level_escaping_root_produces_no_edge(tmp_path):
    """A relative import whose level pops ABOVE the project root has no internal
    target — the resolver must NOT fabricate one."""
    sub = _make_proj(tmp_path)
    # ``proj/sub`` is 2 packages deep; level=3 escapes the analyzed tree.
    (sub / "e.py").write_text("from ... import escape\n")
    edges = _edges(tmp_path)
    assert all(src != "proj/sub/e.py" for src, _ in edges)


def test_relative_import_cycle_is_now_detected(tmp_path):
    """A relative-import cycle (``x`` <-> ``y`` via ``from .y`` / ``from .x``)
    in one package is detected — previously hidden because both edges were
    dropped/phantom."""
    sub = _make_proj(tmp_path)
    (sub / "x.py").write_text("from .y import yfn\n")
    (sub / "y.py").write_text("from .x import xfn\n")
    builder = DependencyGraphBuilder(tmp_path)
    cycles = builder.find_cycles(limit=10)
    cycle_sets = {frozenset(c) for c in cycles}
    assert frozenset({"proj/sub/x.py", "proj/sub/y.py"}) in cycle_sets


def test_absolute_imports_are_byte_identical(tmp_path):
    """Absolute-import resolution is untouched: ``from pkg import sub`` -> the
    submodule file, ``from pkg import symbol`` -> the package ``__init__.py``,
    no double-counting. (Mirrors the absolute-import invariant suite.)"""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def func():\n    return 1\n")
    (pkg / "sub.py").write_text("x = 1\n")
    (pkg / "a.py").write_text("from pkg import sub, func\n")
    edges = _edges(tmp_path)
    assert edges == [("pkg/a.py", "pkg/__init__.py"), ("pkg/a.py", "pkg/sub.py")]


def test_resolution_is_deterministic_across_runs(tmp_path):
    """Same input -> same edges across two independent builders (no clock/random,
    sorted candidates)."""
    sub = _make_proj(tmp_path)
    (sub / "b.py").write_text("fb = 1\n")
    (sub / "c.py").write_text("from .b import fb\n")
    (sub / "d.py").write_text("from . import b\n")
    (tmp_path / "proj" / "pkg.py").write_text("y = 1\n")
    (sub / "e.py").write_text("from ..pkg import y\n")
    first = _edges(tmp_path)
    second = _edges(tmp_path)
    assert first == second
    assert ("proj/sub/c.py", "proj/sub/b.py") in first
    assert ("proj/sub/d.py", "proj/sub/b.py") in first
    assert ("proj/sub/e.py", "proj/pkg.py") in first
