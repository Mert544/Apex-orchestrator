"""apex changelog: release notes backed by artifacts, never by memory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from app.reporting.changelog import build_changelog


def _repo(tmp_path: Path, tag: bool = True) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")

    def _git(*args: str) -> None:
        env = dict(os.environ)
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "initial release")
    if tag:
        _git("tag", "v1.0.0")
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 2\n")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "feat: double the answer")
    return tmp_path


def test_commits_since_last_tag(tmp_path):
    _repo(tmp_path)
    md = build_changelog(tmp_path)
    assert "## Changes since `v1.0.0`" in md
    assert "- feat: double the answer" in md
    assert "initial release" not in md          # pre-tag history excluded
    assert "written from evidence" in md


def test_untagged_repo_says_so(tmp_path):
    _repo(tmp_path, tag=False)
    md = build_changelog(tmp_path)
    assert "no release tag yet" in md
    assert "- initial release" in md


def test_verified_fixes_come_from_the_proof(tmp_path):
    _repo(tmp_path)
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(json.dumps({"fixes": [
        {"outcome": "applied",
         "finding": {"action": "harden_security", "target": "app/danger.py"},
         "verification": {"strength": {"level": "module"}},
         "shield_test": "tests/test_danger.py"},
        {"outcome": "blocked",
         "finding": {"action": "harden_security", "target": "app/x.py"}},
    ]}))
    md = build_changelog(tmp_path)
    assert "## Verified fixes" in md
    assert "**harden_security** on `app/danger.py`" in md
    assert "suite covers the module" in md and "shielded by `tests/test_danger.py`" in md
    assert "app/x.py" not in md                  # blocked work is not a release note


def test_health_section_present(tmp_path):
    _repo(tmp_path)
    assert "## Health: **" in build_changelog(tmp_path)


def test_empty_dir_renders_calmly(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    md = build_changelog(tmp_path)
    assert "Release notes" in md  # health still renders; never crashes


def test_cli_changelog_writes_out(tmp_path, capsys):
    from app.cli import cmd_changelog

    _repo(tmp_path)
    out = tmp_path / "NOTES.md"
    rc = cmd_changelog(argparse.Namespace(target=str(tmp_path), out=str(out)))
    assert rc == 0
    assert "feat: double the answer" in out.read_text(encoding="utf-8")
    assert "[changelog] Written to" in capsys.readouterr().out
