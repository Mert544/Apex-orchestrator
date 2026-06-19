"""Regression: import STYLE must not change the structural graph.

A confirmed P1 correctness defect blinded Apex's entire Architecture pillar:
``_import_names`` recorded only the PACKAGE for ``from pkg import submodule``,
discarding the submodule. The resolver then collapsed every cross-module edge
that used the dominant ``from pkg import submodule`` idiom onto ``pkg/__init__.py``,
so ``find_cycles``, fan-in/hub ranking, and fragile-module detection silently
missed real structure. An identical toy project graded differently depending
ONLY on ``import a.b`` vs ``from a import b``.

These tests pin the invariant: building the SAME toy package two ways — once
with ``import``-style, once with ``from``-style — yields BYTE-IDENTICAL
Architecture results (same import cycles, same hub fan-in, same fragile modules,
same Architecture grade component).
"""

from __future__ import annotations

from pathlib import Path

from app.tools.dependency_graph import DependencyGraphBuilder
from app.tools.project_profile import ProjectProfiler


def _make_pkg(root: Path, *, style: str) -> None:
    """Build the SAME a->b->c->a cycle + hub tree under ``root`` in one style.

    ``hub`` imports a, b and c (high fan-in target c); a->b->c->a closes a
    3-node cycle; ``leaf`` imports nothing. ``style`` is ``"import"`` (``import
    pkg.b``) or ``"from"`` (``from pkg import b``) — the two idioms MUST yield
    the same graph.
    """
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    if style == "import":
        (pkg / "hub.py").write_text("import pkg.a\nimport pkg.b\nimport pkg.c\n")
        (pkg / "a.py").write_text("import pkg.b\n")
        (pkg / "b.py").write_text("import pkg.c\n")
        (pkg / "c.py").write_text("import pkg.a\n")
    elif style == "from":
        (pkg / "hub.py").write_text(
            "from pkg import a\nfrom pkg import b\nfrom pkg import c\n"
        )
        (pkg / "a.py").write_text("from pkg import b\n")
        (pkg / "b.py").write_text("from pkg import c\n")
        (pkg / "c.py").write_text("from pkg import a\n")
    else:  # pragma: no cover - guard against a typo'd parametrization
        raise ValueError(style)
    (pkg / "leaf.py").write_text("x = 1\n")


def _graph_snapshot(root: Path):
    """Deterministic, hashable summary of the Architecture-relevant graph facts.

    Pins sorted edges, sorted in/out degrees, the de-duplicated cycle set, and
    the hub ranking with each hub's fan-in — exactly the inputs that feed the
    Architecture grade component.
    """
    builder = DependencyGraphBuilder(root)
    graph = builder.build()
    edges = sorted(
        (path, tuple(sorted(node.imports)), tuple(sorted(node.imported_by)))
        for path, node in graph.items()
    )
    cycles = sorted(tuple(sorted(set(c))) for c in builder.find_cycles(limit=10))
    hub_fanin = sorted((path, node.in_degree) for path, node in graph.items())
    hubs = tuple(builder.top_central_modules(limit=5))
    return (tuple(edges), tuple(cycles), tuple(hub_fanin), hubs)


def _profile_snapshot(root: Path):
    """The Architecture-pillar profile fields, made hashable for comparison."""
    profile = ProjectProfiler(root).profile()
    return (
        tuple(tuple(c) for c in profile.import_cycles),
        tuple(profile.fragile_modules),
        profile.fragile_count,
        tuple(profile.dependency_hubs),
        tuple(sorted(profile.module_fanin.items())),
    )


def test_from_style_resolves_submodule_not_package(tmp_path):
    """``from pkg import sub`` resolves to ``pkg/sub.py``, not ``pkg/__init__.py``."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("from pkg import b\n")
    (tmp_path / "pkg" / "b.py").write_text("x = 1\n")
    edges = sorted((e.source, e.target) for e in DependencyGraphBuilder(tmp_path).edges())
    assert ("pkg/a.py", "pkg/b.py") in edges
    assert ("pkg/a.py", "pkg/__init__.py") not in edges


def test_from_style_symbol_import_falls_back_to_package(tmp_path):
    """``from pkg import func`` (a SYMBOL, not a submodule) still resolves to
    ``pkg/__init__.py`` via the resolver's pop-to-package fallback, and creates
    exactly ONE edge (no double-counting)."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "pkg" / "a.py").write_text("from pkg import helper\n")
    edges = sorted((e.source, e.target) for e in DependencyGraphBuilder(tmp_path).edges())
    assert edges == [("pkg/a.py", "pkg/__init__.py")]


def test_mixed_submodule_and_symbol_import_does_not_double_count(tmp_path):
    """A single ``from pkg import sub, func`` resolves the submodule to its file
    and the symbol to the package — two DISTINCT real targets, not a spurious
    duplicate edge."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("def func():\n    return 1\n")
    (tmp_path / "pkg" / "sub.py").write_text("x = 1\n")
    (tmp_path / "pkg" / "a.py").write_text("from pkg import sub, func\n")
    edges = sorted((e.source, e.target) for e in DependencyGraphBuilder(tmp_path).edges())
    assert edges == [("pkg/a.py", "pkg/__init__.py"), ("pkg/a.py", "pkg/sub.py")]


def test_import_style_does_not_change_graph(tmp_path):
    """``import pkg.b`` and ``from pkg import b`` build the IDENTICAL graph:
    same edges, same cycles, same hub fan-in. This is the core invariant the
    P1 defect violated."""
    import_root = tmp_path / "import_style"
    from_root = tmp_path / "from_style"
    import_root.mkdir()
    from_root.mkdir()
    _make_pkg(import_root, style="import")
    _make_pkg(from_root, style="from")

    import_snap = _graph_snapshot(import_root)
    from_snap = _graph_snapshot(from_root)

    # Sanity: the import-style graph really does see the cycle + hub.
    _edges, cycles, _hub_fanin, hubs = import_snap
    assert any(len(set(c)) == 3 for c in cycles)  # a->b->c->a
    assert hubs  # a hub exists

    assert import_snap == from_snap


def test_import_style_does_not_change_architecture_profile(tmp_path):
    """The whole Architecture-pillar profile (import_cycles, fragile_modules,
    fragile_count, dependency_hubs, module_fanin) is BYTE-IDENTICAL across the
    two import idioms — so the Architecture grade component cannot shift with
    import style."""
    import_root = tmp_path / "import_style"
    from_root = tmp_path / "from_style"
    import_root.mkdir()
    from_root.mkdir()
    _make_pkg(import_root, style="import")
    _make_pkg(from_root, style="from")

    assert _profile_snapshot(import_root) == _profile_snapshot(from_root)
