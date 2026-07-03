import os

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

    target = tmp_path / "main.py"
    target.write_text("x = 1\n", encoding="utf-8")
    analyzer.analyze(["main.py"])

    first = target.stat()
    target.write_text("x = 2\n", encoding="utf-8")
    # P4 (docs/rnd/context-fragile-tests.md #7): pin the mtime back to the FIRST
    # write's exact value instead of sleeping for a newer one — detection must
    # key on the content hash, so it holds even when the mtime does not tick at
    # all (the worst coarse-mtime filesystem case). Stricter than the sleep.
    os.utime(target, ns=(first.st_atime_ns, first.st_mtime_ns))
    result = analyzer.analyze(["main.py"])

    assert "main.py" in result.changed_files
    assert not result.new_files


def test_incremental_same_content_rewrite_is_unchanged(tmp_path):
    # P4 companion (docs/rnd/context-fragile-tests.md #7): the mirror edge — a
    # rewrite with IDENTICAL content but a strictly newer mtime must land in
    # unchanged_files, proving mtime plays no part in change detection.
    (tmp_path / ".apex").mkdir(parents=True, exist_ok=True)
    analyzer = IncrementalAnalyzer(tmp_path)

    target = tmp_path / "main.py"
    target.write_text("x = 1\n", encoding="utf-8")
    analyzer.analyze(["main.py"])

    first = target.stat()
    target.write_text("x = 1\n", encoding="utf-8")
    os.utime(target, ns=(first.st_atime_ns, first.st_mtime_ns + 5_000_000_000))
    result = analyzer.analyze(["main.py"])

    assert "main.py" in result.unchanged_files
    assert not result.changed_files
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
