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
