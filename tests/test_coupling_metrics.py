"""Tests for app.tools.coupling_metrics.

Hermetic: each test materializes a throwaway package tree under ``tmp_path`` and
asserts the deterministic Ca / Ce / Instability output. No git, clock, or network.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.coupling_metrics import (
    CouplingMetrics,
    ModuleCoupling,
    analyze_coupling,
)


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _by_module(metrics: CouplingMetrics) -> dict[str, ModuleCoupling]:
    return {m.module: m for m in metrics.modules}


def _project(root: Path) -> None:
    """A imports B and C; B and C are leaves with no internal deps."""
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/a.py", "from pkg import b\nimport pkg.c\n")
    _write(root, "pkg/b.py", "x = 1\n")
    _write(root, "pkg/c.py", "y = 2\n")


def test_afferent_and_efferent_counts(tmp_path: Path) -> None:
    _project(tmp_path)
    by = _by_module(analyze_coupling(tmp_path))

    # A imports both B and C -> Ce == 2, and nobody imports A -> Ca == 0.
    assert by["pkg.a"].ce == 2
    assert by["pkg.a"].ca == 0

    # B and C are each imported by A -> Ca >= 1, and import nothing -> Ce == 0.
    assert by["pkg.b"].ca >= 1
    assert by["pkg.c"].ca >= 1
    assert by["pkg.b"].ce == 0
    assert by["pkg.c"].ce == 0


def test_instability_math(tmp_path: Path) -> None:
    _project(tmp_path)
    by = _by_module(analyze_coupling(tmp_path))

    # A: Ce=2, Ca=0 -> I = 2/(0+2) = 1.0 (maximally unstable).
    assert by["pkg.a"].instability == 1.0
    # B: Ce=0, Ca=1 -> I = 0/(1+0) = 0.0 (maximally stable).
    assert by["pkg.b"].instability == 0.0
    assert by["pkg.c"].instability == 0.0


def test_leaf_with_no_deps_instability_zero(tmp_path: Path) -> None:
    # A fully isolated module: Ca + Ce == 0, so I is defined as 0 (no div-by-zero).
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/lonely.py", "import os\nimport json\n")
    by = _by_module(analyze_coupling(tmp_path))

    assert by["pkg.lonely"].ca == 0
    assert by["pkg.lonely"].ce == 0
    assert by["pkg.lonely"].instability == 0.0


def test_relative_imports_resolve_internal(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from . import b\nfrom .sub import deep\n")
    _write(tmp_path, "pkg/b.py", "z = 0\n")
    _write(tmp_path, "pkg/sub/__init__.py")
    _write(tmp_path, "pkg/sub/deep.py", "w = 0\n")
    by = _by_module(analyze_coupling(tmp_path))

    assert by["pkg.a"].ce == 2
    assert by["pkg.b"].ca >= 1
    assert by["pkg.sub.deep"].ca >= 1


def test_stdlib_and_third_party_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "import os\nimport numpy\nfrom collections import OrderedDict\n")
    by = _by_module(analyze_coupling(tmp_path))

    # None of those resolve to internal modules.
    assert by["pkg.a"].ce == 0
    assert by["pkg.a"].instability == 0.0


def test_empty_project_is_safe(tmp_path: Path) -> None:
    result = analyze_coupling(tmp_path)
    assert isinstance(result, CouplingMetrics)
    assert result.modules == []
    assert result.most_unstable == []
    assert result.most_stable == []
    assert result.module_count == 0


def test_highlights_partition_and_cap(tmp_path: Path) -> None:
    _project(tmp_path)
    result = analyze_coupling(tmp_path)

    # Coupling-bearing modules only; capped at 15.
    assert all((m.ca + m.ce) > 0 for m in result.most_unstable)
    assert all((m.ca + m.ce) > 0 for m in result.most_stable)
    assert len(result.most_unstable) <= 15
    assert len(result.most_stable) <= 15

    # Most-unstable leads with A (I=1.0); most-stable leads with a leaf (I=0.0).
    assert result.most_unstable[0].module == "pkg.a"
    assert result.most_stable[0].instability == 0.0


def test_determinism(tmp_path: Path) -> None:
    _project(tmp_path)
    first = analyze_coupling(tmp_path)
    second = analyze_coupling(tmp_path)
    assert first.modules == second.modules
    assert first.most_unstable == second.most_unstable
    assert first.most_stable == second.most_stable


def test_unparseable_file_is_node_without_edges(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/broken.py", "def (:\n")  # syntax error
    _write(tmp_path, "pkg/ok.py", "import pkg.broken\n")
    by = _by_module(analyze_coupling(tmp_path))

    # broken is still a node; it contributes no efferent edges.
    assert "pkg.broken" in by
    assert by["pkg.broken"].ce == 0
    # ok importing broken makes broken's Ca >= 1.
    assert by["pkg.broken"].ca >= 1
