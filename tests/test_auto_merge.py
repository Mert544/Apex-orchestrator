import subprocess

from app.automation.auto_merge import AutoMerger, MergeResult


def _init_repo(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
    )


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
    assert not result.errors


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


def test_branch_create_failure_aborts(tmp_path):
    # An invalid branch name makes `git checkout -b` fail with an error that does
    # NOT contain "already exists" -> the commit must abort with that error.
    _init_repo(tmp_path)
    (tmp_path / "f.py").write_text("x = 2\n", encoding="utf-8")

    merger = AutoMerger(tmp_path)
    result = merger.commit_patches(["f.py"], message="patch", branch="bad..name")

    assert result.success is False
    assert any("failed to create branch" in e.lower() for e in result.errors)
    # No commit hash recorded because we bailed before committing.
    assert result.commit_hash == ""


def test_existing_branch_is_reused_not_failed(tmp_path):
    # Pre-create the branch so `checkout -b` fails with "already exists"; the
    # merger should swallow that and proceed to `checkout <branch>`.
    _init_repo(tmp_path)
    subprocess.run(["git", "branch", "feature-y"], cwd=tmp_path, capture_output=True)
    (tmp_path / "f.py").write_text("x = 3\n", encoding="utf-8")

    merger = AutoMerger(tmp_path)
    result = merger.commit_patches(["f.py"], message="patch", branch="feature-y")

    assert result.success is True
    assert result.branch == "feature-y"
    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    assert current == "feature-y"


def test_checkout_failure_after_create_is_reported(tmp_path, monkeypatch):
    # Force the second `git checkout <branch>` to fail to exercise the checkout
    # error branch independently of branch creation.
    _init_repo(tmp_path)
    merger = AutoMerger(tmp_path)

    real_run_git = merger._run_git

    def fake_run_git(*args):
        if args[:2] == ("checkout", "feature-z"):
            return 1, "", "fatal: could not checkout"
        if args[:2] == ("checkout", "-b"):
            return 0, "", ""  # pretend branch creation succeeded
        return real_run_git(*args)

    monkeypatch.setattr(merger, "_run_git", fake_run_git)
    result = merger.commit_patches(["f.py"], message="patch", branch="feature-z")

    assert result.success is False
    assert any("failed to checkout branch" in e.lower() for e in result.errors)


def test_generic_commit_failure_is_reported(tmp_path, monkeypatch):
    # A commit failure whose message is NOT "nothing to commit" must be surfaced
    # verbatim as a generic commit error.
    _init_repo(tmp_path)
    (tmp_path / "f.py").write_text("x = 9\n", encoding="utf-8")
    merger = AutoMerger(tmp_path)

    real_run_git = merger._run_git

    def fake_run_git(*args):
        if "commit" in args:
            return 1, "", "fatal: unable to write commit object"
        return real_run_git(*args)

    monkeypatch.setattr(merger, "_run_git", fake_run_git)
    result = merger.commit_patches(["f.py"], message="patch")

    assert result.success is False
    assert any("commit failed" in e.lower() for e in result.errors)
    assert any("unable to write commit object" in e.lower() for e in result.errors)


def test_push_uses_current_branch_when_unspecified(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    merger = AutoMerger(tmp_path)

    seen = {}

    def fake_run_git(*args):
        if args[:2] == ("branch", "--show-current"):
            return 0, "main\n", ""
        if args[0] == "push":
            seen["push_args"] = args
            return 0, "", ""
        return 1, "", ""

    monkeypatch.setattr(merger, "_run_git", fake_run_git)
    ok, err = merger.push()

    assert ok is True
    assert err == ""
    # Falls back to the detected current branch ("main") when none is passed.
    assert seen["push_args"] == ("push", "origin", "main")


def test_merge_result_defaults():
    result = MergeResult()
    assert result.success is False
    assert result.commit_hash == ""
    assert result.branch == ""
    assert result.errors == []
