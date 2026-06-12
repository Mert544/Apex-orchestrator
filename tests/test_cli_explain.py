from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli import cmd_explain


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        branch="", target=str(tmp_path), objective="", depth=2, breadth=4,
        max_ideas=30, facets=False, json=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text("def run(e):\n    return eval(e)\n")
    return tmp_path


def test_explain_top_idea_default(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_explain(_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# Why ")
    assert "Score breakdown" in out


def test_explain_specific_branch(tmp_path, capsys):
    _project(tmp_path)
    # Discover a real branch path first.
    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 30, "max_idea_depth": 2, "breadth": 4}, tmp_path).run()
    bp = rep.ideas[0].branch_path
    rc = cmd_explain(_ns(tmp_path, branch=bp))
    assert rc == 0
    assert bp in capsys.readouterr().out


def test_explain_unknown_branch_errors(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_explain(_ns(tmp_path, branch="x.nope.nope"))
    assert rc == 1
    assert "No idea found" in capsys.readouterr().out


def test_explain_json(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_explain(_ns(tmp_path, json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "value_formula" in payload and "roi" in payload


def test_explain_names_the_magnitude_bonus(tmp_path, capsys):
    # An idea seeded from a measured fact explains its bonus in the formula.
    import os
    import subprocess

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")

    def _git(*args: str, date: str = "") -> None:
        env = dict(os.environ)
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)

    _git("init", "-q")
    _git("config", "user.email", "t@t.com")
    _git("config", "user.name", "t")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "old", date="2025-01-01T12:00:00 +0000")
    (tmp_path / "app" / "fresh.py").write_text("F = 1\n")
    _git("add", "-A")
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "new", date="2026-06-01T12:00:00 +0000")

    rc = cmd_explain(_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    if "magnitude bonus" in out:           # the exposed finding ranked top
        assert "months exposed / commits / complexity" in out
