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


def test_unparseable_file_is_dropped_returns_none(tmp_path: Path):
    good = tmp_path / "good.py"
    good.write_text("def ok():\n    return 1\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    pass\n", encoding="utf-8")  # SyntaxError

    analyzer = PythonStructureAnalyzer(tmp_path)
    # The unparseable module is dropped (None) rather than raising...
    assert analyzer._analyze_file(bad) is None
    # ...while the valid module survives.
    paths = {m.path for m in analyzer.analyze()}
    assert "good.py" in paths
    assert "bad.py" not in paths


def test_narrowed_except_does_not_swallow_unrelated_error(tmp_path: Path):
    analyzer = PythonStructureAnalyzer(tmp_path)
    # A non-Path argument triggers AttributeError on .read_text, which is NOT in
    # the narrowed (SyntaxError, OSError, ValueError) tuple, so it surfaces
    # instead of being silently turned into None.
    import pytest

    with pytest.raises(AttributeError):
        analyzer._analyze_file(object())  # type: ignore[arg-type]
