"""Tests for ``scripts/merge_train.py`` against a real throwaway git repo.

Each test builds an isolated git repo in ``tmp_path`` (deterministic identity,
gpg-signing off), copies ``merge_train.py`` into its ``scripts/`` dir so the
script's ``ROOT`` resolves to the temp repo, and drives it via ``subprocess`` —
exactly how the dev team would run it. The gate (``scripts/verify.py``) is always
kept out of the test path with ``--no-gate``.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MERGE_TRAIN_SRC = REPO_ROOT / "scripts" / "merge_train.py"


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )


def _commit(repo: Path, message: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", message],
        cwd=repo,
        capture_output=True,
    )


def _head(repo: Path) -> str:
    return _run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _build_repo(tmp_path: Path) -> Path:
    """A repo with a base commit on ``main`` plus a copy of merge_train.py."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "t@t.com")
    _run_git(repo, "config", "user.name", "T")

    # Base tree: an existing tracked file the "modify" branch will touch.
    (repo / "existing.py").write_text("x = 1\n", encoding="utf-8")
    # A self-contained scripts/ dir so the script's ROOT == this repo.
    (repo / "scripts").mkdir()
    shutil.copy2(MERGE_TRAIN_SRC, repo / "scripts" / "merge_train.py")
    # A minimal app package so `from app.engine.work_partition import ...` resolves.
    _install_app_stub(repo)

    _run_git(repo, "add", "-A")
    _commit(repo, "base")
    return repo


def _install_app_stub(repo: Path) -> None:
    """Copy the real app.engine.work_partition (+ its deps) into the temp repo.

    merge_train imports ``app.engine.work_partition.partition_work``; rather than
    re-implement it, vendor the real modules so the planning path runs end-to-end.
    """
    for rel in (
        "app/__init__.py",
        "app/engine/__init__.py",
        "app/engine/work_partition.py",
        "app/engine/blast_radius.py",
        "app/engine/skip_dirs.py",
        "app/tools/__init__.py",
        "app/tools/dependency_graph.py",
        "app/tools/test_linker.py",
        "app/tools/python_structure.py",
    ):
        src = REPO_ROOT / rel
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dst)
        else:
            dst.write_text("", encoding="utf-8")


def _branch_adding_new_file(repo: Path) -> None:
    _run_git(repo, "checkout", "-b", "worktree-agent-newfile", "main")
    (repo / "brand_new.py").write_text("y = 2\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _commit(repo, "add brand_new.py")
    _run_git(repo, "checkout", "main")


def _branch_modifying_existing(repo: Path) -> None:
    _run_git(repo, "checkout", "-b", "worktree-agent-modify", "main")
    (repo / "existing.py").write_text("x = 99\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _commit(repo, "modify existing.py")
    _run_git(repo, "checkout", "main")


def _run_train(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/merge_train.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #


def test_new_file_branch_is_ordered_first(tmp_path):
    repo = _build_repo(tmp_path)
    _branch_adding_new_file(repo)
    _branch_modifying_existing(repo)

    proc = _run_train(
        repo, "worktree-agent-modify", "worktree-agent-newfile", "--dry-run"
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout

    # The add-only branch precedes the modifying branch in the integration order.
    new_idx = out.index("worktree-agent-newfile")
    mod_idx = out.index("worktree-agent-modify")
    assert new_idx < mod_idx
    # The new-file branch is classified add-only; the modify branch is not.
    assert "## Add-only" in out
    assert "brand_new.py" in out
    assert "existing.py" in out


# --------------------------------------------------------------------------- #
# Dry run changes nothing
# --------------------------------------------------------------------------- #


def test_dry_run_changes_nothing(tmp_path):
    repo = _build_repo(tmp_path)
    _branch_adding_new_file(repo)
    _branch_modifying_existing(repo)

    before = _head(repo)
    proc = _run_train(
        repo, "worktree-agent-newfile", "worktree-agent-modify", "--dry-run"
    )
    assert proc.returncode == 0, proc.stderr
    assert "Merge Train Plan" in proc.stdout
    assert "integration order" in proc.stdout

    after = _head(repo)
    assert before == after  # HEAD unchanged
    # No file was actually created/modified by the dry run.
    assert not (repo / "brand_new.py").exists()
    assert (repo / "existing.py").read_text(encoding="utf-8") == "x = 1\n"
    # Working tree is clean (dry run staged/committed nothing).
    status = _run_git(repo, "status", "--porcelain").stdout.strip()
    assert status == ""


def test_dry_run_is_idempotent(tmp_path):
    repo = _build_repo(tmp_path)
    _branch_adding_new_file(repo)
    _branch_modifying_existing(repo)

    a = _run_train(repo, "worktree-agent-modify", "worktree-agent-newfile", "--dry-run")
    b = _run_train(repo, "worktree-agent-modify", "worktree-agent-newfile", "--dry-run")
    assert a.returncode == 0 and b.returncode == 0
    # Deterministic: same input -> byte-identical plan.
    assert a.stdout == b.stdout


# --------------------------------------------------------------------------- #
# Clean integration
# --------------------------------------------------------------------------- #


def test_clean_run_cherry_picks_and_leaves_tree_clean(tmp_path):
    repo = _build_repo(tmp_path)
    _branch_adding_new_file(repo)
    _branch_modifying_existing(repo)

    before = _head(repo)
    proc = _run_train(
        repo, "worktree-agent-newfile", "worktree-agent-modify", "--no-gate"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "MERGE TRAIN SUMMARY" in out
    assert "gate: SKIPPED" in out

    # Both refs touch disjoint files, so both cherry-pick cleanly.
    assert "+ worktree-agent-newfile" in out
    assert "+ worktree-agent-modify" in out
    assert "conflicted — need manual merge (0)" in out

    # The picks actually landed on HEAD.
    after = _head(repo)
    assert after != before
    assert (repo / "brand_new.py").exists()
    assert (repo / "existing.py").read_text(encoding="utf-8") == "x = 99\n"
    # Working tree is clean — no dangling cherry-pick state.
    status = _run_git(repo, "status", "--porcelain").stdout.strip()
    assert status == ""
    assert not (repo / ".git" / "CHERRY_PICK_HEAD").exists()


# --------------------------------------------------------------------------- #
# Conflict is reported, never auto-resolved
# --------------------------------------------------------------------------- #


def test_conflicting_pair_is_reported_and_left_clean(tmp_path):
    repo = _build_repo(tmp_path)

    # Two branches that both modify the SAME existing file in incompatible ways:
    # the second cannot cherry-pick onto the first without a conflict.
    _run_git(repo, "checkout", "-b", "worktree-agent-confa", "main")
    (repo / "existing.py").write_text("x = 'A'\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _commit(repo, "set A")
    _run_git(repo, "checkout", "main")

    _run_git(repo, "checkout", "-b", "worktree-agent-confb", "main")
    (repo / "existing.py").write_text("x = 'B'\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _commit(repo, "set B")
    _run_git(repo, "checkout", "main")

    before = _head(repo)
    proc = _run_train(
        repo, "worktree-agent-confa", "worktree-agent-confb", "--no-gate"
    )
    # A conflicted ref makes the run exit non-zero.
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = proc.stdout

    # First pick lands; second conflicts on the shared file and is reported.
    assert "+ worktree-agent-confa" in out
    assert "! worktree-agent-confb" in out
    assert "existing.py" in out  # the overlapping file is surfaced
    assert "conflicted — need manual merge (1)" in out

    # The conflict was aborted, NOT auto-resolved: tree is clean, no mid-pick.
    status = _run_git(repo, "status", "--porcelain").stdout.strip()
    assert status == ""
    assert not (repo / ".git" / "CHERRY_PICK_HEAD").exists()
    # The first (clean) pick still advanced HEAD; the conflicting one did not
    # corrupt the tree.
    after = _head(repo)
    assert after != before
    content = (repo / "existing.py").read_text(encoding="utf-8")
    assert content == "x = 'A'\n"  # confa landed, confb was aborted


# --------------------------------------------------------------------------- #
# Empty / no-ref path
# --------------------------------------------------------------------------- #


def test_no_refs_is_a_noop(tmp_path):
    repo = _build_repo(tmp_path)
    before = _head(repo)
    proc = _run_train(repo, "--no-gate")
    assert proc.returncode == 0
    assert "no refs to integrate" in proc.stdout
    assert _head(repo) == before


def test_auto_discovers_ahead_branches(tmp_path):
    repo = _build_repo(tmp_path)
    _branch_adding_new_file(repo)
    _branch_modifying_existing(repo)

    proc = _run_train(repo, "--auto", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    # Both worktree-agent-* branches are discovered automatically.
    assert "worktree-agent-newfile" in out
    assert "worktree-agent-modify" in out
