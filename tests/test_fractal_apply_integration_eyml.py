"""`apex fractal analyze --apply/--commit` — UNMOCKED end-to-end.

Every existing fractal-apply test mocks git_commit / gates / patch_result, so none
could catch the project_root drop, the git_commit misdirection, or the
severity-gate that structurally blocked docstring/test findings. These tests run
the REAL pipeline against a REAL tmp git repo whose path is DELIBERATELY not the
process CWD, so a landed patch / commit in the target (and an untouched CWD) is the
proof that project_root is threaded end-to-end.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from app.cli_reporting import cmd_fractal


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _make_repo(root: Path, body: str = "def add(a, b):\n    return a + b\n") -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "m.py").write_text(body, encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")


def _ns(**ov) -> argparse.Namespace:
    base = dict(subcommand="analyze", target="", depth=3, json=False,
                max_fractal_budget=None, agent="docstring", apply=False,
                commit=False, mode=None)
    base.update(ov)
    return argparse.Namespace(**base)


def test_apply_lands_docstring_in_target_not_cwd(tmp_path, monkeypatch, capsys):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = tmp_path / "proj"
    _make_repo(target)
    monkeypatch.chdir(cwd)  # CWD deliberately != target

    rc = cmd_fractal(_ns(target=str(target), agent="docstring", apply=True))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Applied" in out
    # The docstring landed in the TARGET file — proof project_root is threaded.
    assert '"""' in (target / "pkg" / "m.py").read_text(encoding="utf-8")
    # CWD is untouched — no source tree leaked there.
    assert not (cwd / "pkg").exists()


def test_apply_lands_on_cache_hit_too(tmp_path, monkeypatch):
    # A second run over the same finding hits the (CWD-persistent) fractal cache;
    # the cache-hit path must land the SAME correct patch, not a fallback template.
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    target = tmp_path / "proj"
    _make_repo(target)

    cmd_fractal(_ns(target=str(target), agent="docstring", apply=True))
    _git(target, "checkout", "-q", "--", ".")  # reset the working tree
    cmd_fractal(_ns(target=str(target), agent="docstring", apply=True))  # cache hit
    assert '"""' in (target / "pkg" / "m.py").read_text(encoding="utf-8")


def test_commit_lands_in_target_repo(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    target = tmp_path / "proj"
    _make_repo(target)

    before = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=target,
                            capture_output=True, text=True).stdout.strip()
    cmd_fractal(_ns(target=str(target), agent="docstring", apply=True, commit=True))
    after = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=target,
                           capture_output=True, text=True).stdout.strip()
    # The commit landed in the TARGET repo (git_commit rebind), not the CWD.
    assert int(after) == int(before) + 1


def test_commit_blocked_on_dirty_target(tmp_path, monkeypatch, capsys):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    target = tmp_path / "proj"
    _make_repo(target)
    (target / "pkg" / "dirty.py").write_text("x = 1\n", encoding="utf-8")  # untracked → dirty

    rc = cmd_fractal(_ns(target=str(target), agent="docstring", apply=True, commit=True))
    out = capsys.readouterr().out
    assert rc == 1
    assert "dirty" in out.lower()


def test_autonomous_apply_without_commit_blocks_dirty_tree(tmp_path, monkeypatch, capsys):
    # --mode autonomous --apply (no --commit) must ALSO honor the clean-tree gate:
    # the gate keys on the resolved mode's permissions, not the literal --commit.
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    target = tmp_path / "proj"
    _make_repo(target)
    (target / "pkg" / "dirty.py").write_text("x = 1\n", encoding="utf-8")  # untracked → dirty

    rc = cmd_fractal(_ns(target=str(target), agent="docstring", apply=True,
                         commit=False, mode="autonomous"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "dirty" in out.lower()
    # The source was NOT mutated behind the gate.
    assert '"""' not in (target / "pkg" / "m.py").read_text(encoding="utf-8")


def test_commit_on_non_git_target_blocks_and_never_fakes_a_commit(tmp_path, monkeypatch, capsys):
    # A --target that is not a git repo must be BLOCKED (git's error is on stderr,
    # so an empty stdout must not read as "clean") — never mutated, never a false
    # "committed 1".
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    target = tmp_path / "proj"  # deliberately NOT a git repo
    (target / "pkg").mkdir(parents=True)
    (target / "pkg" / "m.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (target / "pkg" / "__init__.py").write_text("", encoding="utf-8")

    rc = cmd_fractal(_ns(target=str(target), agent="docstring", apply=True, commit=True))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not a git repository" in out.lower()
    assert "committed 1" not in out
    assert '"""' not in (target / "pkg" / "m.py").read_text(encoding="utf-8")


def test_report_path_unchanged_for_default_agent(tmp_path, monkeypatch, capsys):
    # Without --apply, nothing is written; the summary still prints (default agent).
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    target = tmp_path / "proj"
    _make_repo(target)

    rc = cmd_fractal(_ns(target=str(target)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Fractal analyzed" in out
    # Report mode never patches.
    assert "Applied" not in out
    assert '"""' not in (target / "pkg" / "m.py").read_text(encoding="utf-8")
