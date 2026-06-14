import time

from app.engine.incremental_analyzer import IncrementalAnalyzer


def test_incremental_detects_new_file(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    analyzer = IncrementalAnalyzer(tmp_path)

    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    result = analyzer.analyze(["main.py"])

    assert "main.py" in result.new_files
    assert not result.changed_files
    assert not result.unchanged_files


def test_incremental_detects_changed_file(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    analyzer = IncrementalAnalyzer(tmp_path)

    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    analyzer.analyze(["main.py"])

    time.sleep(0.01)
    (tmp_path / "main.py").write_text("x = 2\n", encoding="utf-8")
    result = analyzer.analyze(["main.py"])

    assert "main.py" in result.changed_files
    assert not result.new_files


def test_incremental_detects_unchanged_file(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    analyzer = IncrementalAnalyzer(tmp_path)

    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    analyzer.analyze(["main.py"])

    result = analyzer.analyze(["main.py"])
    assert "main.py" in result.unchanged_files


def test_incremental_autodiscovery_ignores_worktree_copies(tmp_path):
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("x = 1\n", encoding="utf-8")
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "real.py").write_text("x = 1\n", encoding="utf-8")

    # files=None triggers auto-discovery of the project tree.
    result = IncrementalAnalyzer(tmp_path).analyze()
    assert "app/real.py" in result.new_files
    assert not any(".claude" in f for f in result.new_files)
