from app.engine.incremental_analyzer import IncrementalAnalyzer


def test_incremental_detects_deleted_file(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    analyzer = IncrementalAnalyzer(tmp_path)

    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    analyzer.analyze(["main.py"])

    (tmp_path / "main.py").unlink()
    result = analyzer.analyze([])

    assert "main.py" in result.deleted_files


def test_incremental_auto_discover_python_files(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("b = 2\n", encoding="utf-8")

    analyzer = IncrementalAnalyzer(tmp_path)
    result = analyzer.analyze()

    assert len(result.new_files) == 2
    assert "src/a.py" in result.new_files or "src\\a.py" in result.new_files
    assert "src/b.py" in result.new_files or "src\\b.py" in result.new_files
