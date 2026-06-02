import subprocess

from app.automation.auto_merge import AutoMerger


def test_auto_merger_creates_commit(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)

    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "main.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

    (tmp_path / "main.py").write_text("x = 2\n", encoding="utf-8")

    merger = AutoMerger(tmp_path)
    result = merger.commit_patches(["main.py"], message="Apply patch")

    assert result.success
    assert result.commit_hash
    assert len(result.errors) == 0


def test_commit_aborts_on_staging_failure(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "main.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()

    # Stage a path that cannot be added -> must abort before committing.
    merger = AutoMerger(tmp_path)
    result = merger.commit_patches(["does/not/exist.py"], message="bad")

    assert result.success is False
    assert result.errors
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    # No new commit was created (HEAD unchanged).
    assert before == after


def test_commit_on_new_branch(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "f.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    (tmp_path / "f.py").write_text("x = 2\n")
    merger = AutoMerger(tmp_path)
    result = merger.commit_patches(["f.py"], message="patch", branch="feature-x")
    assert result.success
    assert result.branch == "feature-x"


def test_commit_nothing_to_commit(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "f.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    # No changes since last commit -> "nothing to commit".
    merger = AutoMerger(tmp_path)
    result = merger.commit_patches(["f.py"], message="noop")
    assert result.success is False
    assert any("no changes to commit" in e.lower() for e in result.errors)


def test_push_no_remote_fails(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "f.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    ok, err = AutoMerger(tmp_path).push()
    assert ok is False  # no remote configured
