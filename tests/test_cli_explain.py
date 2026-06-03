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
