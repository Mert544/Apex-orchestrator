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
