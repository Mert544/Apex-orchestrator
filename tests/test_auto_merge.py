import subprocess

from app.automation.auto_merge import AutoMerger


def test_auto_merger_creates_commit(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)

    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "main.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

    (tmp_path / "main.py").write_text("x = 2\n", encoding="utf-8")

    merger = AutoMerger(tmp_path)
    result = merger.commit_patches(["main.py"], message="Apply patch")

    assert result.success
    assert result.commit_hash
    assert len(result.errors) == 0
