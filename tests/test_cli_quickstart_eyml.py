"""``apex quickstart`` — the 60-second on-ramp, as ONE read-only motion.

Composes ONLY existing engines (``health_score.grade``, the idea/roadmap
engine ``cmd_auto`` already runs, and ``IdeaActionBridge.plan_roadmap``'s
report-mode scout) — invents no new analysis. These tests pin the contract:

  * end-to-end human output carries the health grade, a "safe move(s)" line,
    and the three copy-paste next steps;
  * ``--json`` emits the documented structured dict;
  * STRICTLY READ-ONLY: the target tree (and any ``.apex/``) is byte-for-byte
    unchanged after running, on both the human and ``--json`` paths;
  * a fresh/near-empty project never raises and reports 0 landable moves;
  * determinism: two runs on the same project produce byte-identical output;
  * the command is registered and dispatches to ``cmd_quickstart``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from app.cli_insight import cmd_quickstart


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _build_project(root: Path) -> None:
    """A small, real Python project: a couple of modules plus a linked test —
    enough for the grade + idea engines to have something to say."""
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "mod.py").write_text(
        "def add(x, y):\n"
        "    return x + y\n",
        encoding="utf-8")
    (root / "app" / "other.py").write_text(
        "def greet(name):\n"
        "    return f'hi {name}'\n",
        encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_mod.py").write_text(
        "from app.mod import add\n\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'p'\nversion = '0'\n", encoding="utf-8")


def _ns(target: str, as_json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(target=target, json=as_json)


def _snapshot(root: Path) -> set[tuple[str, bytes]]:
    """Every file under ``root`` (path, content) — including any ``.apex/`` —
    so a stray write of any kind is caught, not just a git-visible one."""
    return {
        (str(p.relative_to(root)), p.read_bytes())
        for p in sorted(root.rglob("*")) if p.is_file()
    }


# --------------------------------------------------------------------------- #
# End-to-end human output
# --------------------------------------------------------------------------- #

def test_quickstart_end_to_end_human_output(tmp_path, capsys):
    _build_project(tmp_path)
    rc = cmd_quickstart(_ns(str(tmp_path)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Zero-token · offline · deterministic · never-fake-green." in out
    assert "## Health:" in out
    assert "safe move(s) available" in out
    assert f"apex grade --target {tmp_path} --diff" in out
    assert f"apex develop --target {tmp_path} --apply" in out
    assert f"apex dashboard --target {tmp_path}" in out


def test_quickstart_default_target_renders_dot(tmp_path, capsys, monkeypatch):
    # No --target given: the next-step commands stay copy-paste valid by
    # falling back to `.` rather than an absolute path.
    _build_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = cmd_quickstart(_ns(""))
    out = capsys.readouterr().out
    assert rc == 0
    assert "apex grade --target . --diff" in out
    assert "apex develop --target . --apply" in out
    assert "apex dashboard --target ." in out


# --------------------------------------------------------------------------- #
# --json contract
# --------------------------------------------------------------------------- #

def test_quickstart_json_has_documented_keys(tmp_path, capsys):
    _build_project(tmp_path)
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(data) == {
        "grade", "breakdown", "top_opportunities", "landable_count", "next_steps",
    }
    assert set(data["grade"]) == {"score", "letter"}
    assert isinstance(data["grade"]["score"], int)
    assert isinstance(data["breakdown"], str) and data["breakdown"]
    assert isinstance(data["top_opportunities"], list)
    assert len(data["top_opportunities"]) <= 3
    for op in data["top_opportunities"]:
        assert set(op) == {"branch_path", "title", "phase", "roi"}
    assert isinstance(data["landable_count"], int) and data["landable_count"] >= 0
    assert data["next_steps"] == [
        f"apex grade --target {tmp_path} --diff",
        f"apex develop --target {tmp_path} --apply",
        f"apex dashboard --target {tmp_path}",
    ]


# --------------------------------------------------------------------------- #
# READ-ONLY
# --------------------------------------------------------------------------- #

def test_quickstart_never_writes_to_target_tree(tmp_path, capsys):
    _build_project(tmp_path)
    before = _snapshot(tmp_path)
    cmd_quickstart(_ns(str(tmp_path)))
    capsys.readouterr()
    cmd_quickstart(_ns(str(tmp_path), as_json=True))
    capsys.readouterr()
    after = _snapshot(tmp_path)
    assert before == after
    assert not (tmp_path / ".apex").exists()


# --------------------------------------------------------------------------- #
# Honest on a fresh/empty project
# --------------------------------------------------------------------------- #

def test_quickstart_on_empty_project_never_raises(tmp_path, capsys):
    # No files at all — the barest possible "fresh project".
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["landable_count"] == 0
    assert data["grade"]["score"] == 100
    assert data["grade"]["letter"] == "A+"
    assert isinstance(data["top_opportunities"], list)


def test_quickstart_engine_failure_degrades_to_honest_empty(tmp_path, capsys, monkeypatch):
    # If the idea engine itself raises (a hostile/unreadable project), the
    # command must still exit 0 with an honest, empty opportunity/landable
    # picture rather than crashing the on-ramp.
    class _BoomEngine:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")

    import app.engine.idea_permutation as idea_permutation

    monkeypatch.setattr(idea_permutation, "IdeaPermutationEngine", _BoomEngine)
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["top_opportunities"] == []
    assert data["landable_count"] == 0


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #

def test_quickstart_is_deterministic(tmp_path, capsys):
    _build_project(tmp_path)
    cmd_quickstart(_ns(str(tmp_path), as_json=True))
    first = capsys.readouterr().out
    cmd_quickstart(_ns(str(tmp_path), as_json=True))
    second = capsys.readouterr().out
    assert first == second

    cmd_quickstart(_ns(str(tmp_path)))
    first_md = capsys.readouterr().out
    cmd_quickstart(_ns(str(tmp_path)))
    second_md = capsys.readouterr().out
    assert first_md == second_md


# --------------------------------------------------------------------------- #
# Registration / dispatch
# --------------------------------------------------------------------------- #

def test_quickstart_is_registered_and_dispatches():
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "quickstart" in sub.choices
    assert sub.choices["quickstart"].get_default("func") is cli_insight.cmd_quickstart


def test_quickstart_help_does_not_raise():
    with pytest.raises(SystemExit) as exc:
        import sys
        from unittest import mock

        with mock.patch.object(sys, "argv", ["apex", "quickstart", "--help"]):
            from app.cli import main

            main()
    assert exc.value.code == 0
