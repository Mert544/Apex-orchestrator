from pathlib import Path

from app.tools.repo_scanner import RepoScanner


def test_repo_scanner_finds_relevant_project_files(tmp_path: Path):
    target = tmp_path / "service.py"
    target.write_text("def calculate_risk():\n    return 'market risk'\n", encoding="utf-8")

    scanner = RepoScanner(root=tmp_path)
    results = scanner.search("market risk calculation", top_k=3)

    assert len(results) >= 1
    assert results[0].path == "service.py"
    assert "market risk" in results[0].snippet.lower()


def test_repo_scanner_ignores_worktree_copies(tmp_path: Path):
    # Real source under the project root.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text(
        "def calculate_risk():\n    return 'market risk'\n", encoding="utf-8"
    )
    # A worktree COPY under .claude/ that must never be scanned.
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "real.py").write_text(
        "def calculate_risk():\n    return 'market risk'\n", encoding="utf-8"
    )

    results = RepoScanner(root=tmp_path).search("market risk calculation", top_k=5)
    paths = {r.path for r in results}
    assert "app/real.py" in {p.replace("\\", "/") for p in paths}
    assert not any(".claude" in p for p in paths)
