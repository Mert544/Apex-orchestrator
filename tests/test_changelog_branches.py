"""apex changelog: branch-level edges — strength words, tagged commit cap, fix-section caps."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import app.reporting.changelog as cl
from app.reporting.changelog import _COMMIT_CAP


def _git(tmp_path: Path, *args: str) -> None:
    env = dict(os.environ)
    subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)


def _init_repo(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-qm", "initial")


def _write_proof(tmp_path: Path, fixes: list[dict]) -> None:
    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    (apex / "proof-of-fix.json").write_text(json.dumps({"fixes": fixes}))


def test_strength_word_function_level(tmp_path):
    """The 'function' strength level renders 'tests name the changed function'."""
    _write_proof(tmp_path, [{
        "outcome": "applied",
        "finding": {"action": "fix", "target": "app/m.py"},
        "verification": {"strength": {"level": "function"}},
    }])
    lines = cl._fixes_section(tmp_path)
    assert any("tests name the changed function" in ln for ln in lines)


def test_strength_word_test_change_level(tmp_path):
    """The 'test-change' strength level renders 'test-only change'."""
    _write_proof(tmp_path, [{
        "outcome": "applied",
        "finding": {"action": "fix", "target": "app/m.py"},
        "verification": {"strength": {"level": "test-change"}},
    }])
    lines = cl._fixes_section(tmp_path)
    assert any("test-only change" in ln for ln in lines)


def test_unknown_strength_level_adds_no_extra(tmp_path):
    """A strength level outside the known map contributes no suffix text."""
    _write_proof(tmp_path, [{
        "outcome": "applied",
        "finding": {"action": "fix", "target": "app/m.py"},
        "verification": {"strength": {"level": "galaxy-brained"}},
    }])
    lines = cl._fixes_section(tmp_path)
    assert "- **fix** on `app/m.py`" in lines
    assert all(" — " not in ln for ln in lines)


def test_shield_only_extra_without_strength(tmp_path):
    """A shield_test alone (no strength) renders just the shielded-by suffix."""
    _write_proof(tmp_path, [{
        "outcome": "applied",
        "finding": {"action": "fix", "target": "app/m.py"},
        "shield_test": "tests/test_shield.py",
    }])
    lines = cl._fixes_section(tmp_path)
    assert any("— shielded by `tests/test_shield.py`" in ln for ln in lines)
    assert all("tests name" not in ln for ln in lines)


def test_missing_finding_uses_question_mark_placeholders(tmp_path):
    """An applied fix with no finding dict falls back to '?' for action and target."""
    _write_proof(tmp_path, [{"outcome": "applied"}])
    lines = cl._fixes_section(tmp_path)
    assert "- **?** on `?`" in lines


def test_fixes_section_caps_at_twelve(tmp_path):
    """No more than 12 applied fixes are listed even when many are present."""
    fixes = [{"outcome": "applied",
              "finding": {"action": "fix", "target": f"app/m{i}.py"}}
             for i in range(20)]
    _write_proof(tmp_path, fixes)
    lines = cl._fixes_section(tmp_path)
    bullets = [ln for ln in lines if ln.startswith("- **")]
    assert len(bullets) == 12


def test_missing_proof_file_returns_empty(tmp_path):
    """No proof-of-fix.json at all yields an empty fixes section (early return)."""
    assert cl._fixes_section(tmp_path) == []


def test_tagged_commit_cap_truncates(tmp_path):
    """More than _COMMIT_CAP commits since a tag still truncates with the marker."""
    _init_repo(tmp_path)
    _git(tmp_path, "tag", "v0.1.0")
    for i in range(_COMMIT_CAP + 5):
        (tmp_path / "app" / "m.py").write_text(f"def f():\n    return {i}\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-qm", f"post-tag {i}")
    lines = cl._commits_section(tmp_path)
    assert lines[0] == "## Changes since `v0.1.0`"
    bullets = [ln for ln in lines if ln.startswith("- ")]
    assert len(bullets) == _COMMIT_CAP + 1
    assert any("and more" in ln for ln in bullets)


def test_no_commits_returns_empty_section(tmp_path):
    """A repo with no log output produces no commits section."""
    # No git repo at all -> _git returns '' -> no subjects.
    assert cl._commits_section(tmp_path) == []
