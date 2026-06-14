from pathlib import Path

from app.tools.python_structure import PythonStructureAnalyzer


def test_python_structure_analyzer_extracts_imports_and_symbols(tmp_path: Path):
    source = tmp_path / "service.py"
    source.write_text(
        "import os\nfrom pathlib import Path\n\nclass Service:\n    pass\n\ndef build_path():\n    return Path('.')\n",
        encoding="utf-8",
    )

    results = PythonStructureAnalyzer(tmp_path).analyze()
    assert len(results) == 1
    module = results[0]
    assert module.path == "service.py"
    assert "os" in module.imports
    assert "pathlib" in module.imports
    assert "Service" in module.symbols
    assert "build_path" in module.symbols


def test_python_structure_ignores_worktree_copies(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def real(): pass\n", encoding="utf-8")
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "copy.py").write_text("def copy(): pass\n", encoding="utf-8")

    results = PythonStructureAnalyzer(tmp_path).analyze()
    paths = {Path(m.path).as_posix() for m in results}
    assert paths == {"app/real.py"}
