from app.tools.dependency_graph import DependencyGraphBuilder


def test_find_cycles_detects_indirect(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import app.b\n")
    (tmp_path / "app" / "b.py").write_text("import app.c\n")
    (tmp_path / "app" / "c.py").write_text("import app.a\n")
    cycles = DependencyGraphBuilder(tmp_path).find_cycles()
    assert cycles
    assert any(len(set(c)) == 3 for c in cycles)


def test_find_cycles_none_when_acyclic(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import app.b\n")
    (tmp_path / "app" / "b.py").write_text("def b():\n    return 1\n")
    assert DependencyGraphBuilder(tmp_path).find_cycles() == []


def test_build_does_not_crash_when_import_target_is_unanalyzed(tmp_path, monkeypatch):
    # The structure analyzer caps at max_files, so an import can resolve (via the
    # all-files module map) to a module the analyzer never turned into a graph
    # node. Building the graph must skip that edge, not KeyError on it.
    import app.tools.dependency_graph as dg
    from app.tools.python_structure import PythonStructureAnalyzer
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("import pkg.zzz_last\n")  # imports a late file
    (tmp_path / "pkg" / "zzz_last.py").write_text("x = 1\n")
    # Cap the analyzer so the (sorted-last) import target is excluded from the
    # graph while the all-files module map still resolves it.
    monkeypatch.setattr(dg, "PythonStructureAnalyzer",
                        lambda root: PythonStructureAnalyzer(root, max_files=2))
    graph = dg.DependencyGraphBuilder(tmp_path).build()   # must not raise
    assert "pkg/zzz_last.py" not in graph                 # excluded by the cap
    assert isinstance(graph, dict)


def test_analyze_file_selection_is_deterministic_under_cap(tmp_path):
    from app.tools.python_structure import PythonStructureAnalyzer
    for i in range(20):
        (tmp_path / f"m{i:02d}.py").write_text("x = 1\n")
    a = PythonStructureAnalyzer(tmp_path, max_files=5)
    first = [s.path for s in a.analyze()]
    second = [s.path for s in PythonStructureAnalyzer(tmp_path, max_files=5).analyze()]
    assert first == second                  # same machine, repeatable
    assert first == sorted(first)           # the deterministic (sorted) prefix
def test_module_map_ignores_worktree_copies(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def real(): pass\n")
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "real.py").write_text("def real(): pass\n")

    mapping = DependencyGraphBuilder(tmp_path)._module_map()
    assert "app.real" in mapping
    assert not any(".claude" in v for v in mapping.values())


def _build_representative_project(root):
    """A small but representative tree: a hub, a 3-node cycle, and a leaf."""
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "hub.py").write_text("import pkg.a\nimport pkg.b\nimport pkg.c\n")
    (pkg / "a.py").write_text("import pkg.b\n")
    (pkg / "b.py").write_text("import pkg.c\n")
    (pkg / "c.py").write_text("import pkg.a\n")  # closes the a->b->c->a cycle
    (pkg / "leaf.py").write_text("x = 1\n")


def _snapshot(builder):
    """Deterministic, hashable summary of the built graph + cycles.

    Pins sorted edges (source -> sorted imports), sorted in/out degrees, the
    node set, and the de-duplicated cycle list — exactly the fields that feed
    hubs, the coordinator, cycle reporting, and the grade.
    """
    graph = builder.build()
    nodes = sorted(graph)
    edges = sorted(
        (path, tuple(sorted(node.imports)), tuple(sorted(node.imported_by)))
        for path, node in graph.items()
    )
    cycles = sorted(tuple(c) for c in builder.find_cycles(limit=10))
    hubs = builder.top_central_modules(limit=5)
    edge_list = sorted((e.source, e.target, e.import_name) for e in builder.edges())
    return (tuple(nodes), tuple(edges), tuple(cycles), tuple(hubs), tuple(edge_list))


def test_build_graph_is_byte_identical_across_repeated_calls(tmp_path):
    # Characterization: every consumer of one builder (build / find_cycles /
    # top_central_modules / edges) must see the SAME graph, and a fresh builder
    # on the same tree must reproduce it bit-for-bit. This pins the memoization
    # against any output drift.
    _build_representative_project(tmp_path)

    builder = DependencyGraphBuilder(tmp_path)
    first = _snapshot(builder)
    # Re-derive from the SAME (now-warm) builder: caches must not change output.
    second = _snapshot(builder)
    # Re-derive from a COLD builder: same tree -> identical result.
    third = _snapshot(DependencyGraphBuilder(tmp_path))

    assert first == second == third

    # And the snapshot is the expected shape (a real cycle + a real hub exist).
    nodes, edges, cycles, hubs, edge_list = first
    assert "pkg/hub.py" in nodes
    assert any(len(set(c)) == 3 for c in cycles)  # a->b->c->a
    assert hubs and hubs[0] in nodes
    assert edge_list  # edges were resolved


def test_build_returns_same_cached_object_on_repeated_calls(tmp_path):
    # The graph is memoized per instance: identical inputs -> the same object,
    # so downstream readers (coordinator, blast radius) never rebuild it.
    _build_representative_project(tmp_path)
    builder = DependencyGraphBuilder(tmp_path)
    assert builder.build() is builder.build()
    # The module map and structures are memoized too.
    assert builder._module_map() is builder._module_map()
    assert builder._structures() is builder._structures()


def test_memoized_helpers_handle_empty_project(tmp_path):
    # Empty/missing-source tree: caches must still work and stay consistent.
    builder = DependencyGraphBuilder(tmp_path)
    assert builder.build() == {}
    assert builder.build() is builder.build()
    assert builder.find_cycles() == []
    assert builder.edges() == []
    assert builder.top_central_modules() == []
    assert builder._module_map() == {}
