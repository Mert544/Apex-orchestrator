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
