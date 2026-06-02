from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli import cmd_fractal, cmd_ideate


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def run(cmd):\n    return eval(cmd)\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp_path


def _ideate_ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        target=str(tmp_path),
        objective="",
        depth=2,
        breadth=3,
        max_ideas=20,
        min_relevance=0.0,
        actions=False,
        top=0,
        draft=False,
        apply=False,
        verify=False,
        commit=False,
        max_apply=0,
        mode="supervised",
        mermaid=False,
        json=False,
        out="",
        kind="",
        roadmap=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_ideate_markdown_and_mermaid(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, mermaid=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "graph" in out.lower() or "```mermaid" in out.lower()


def test_ideate_json_emits_parseable_payload(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ideas" in payload
    assert isinstance(payload["ideas"], list)


def test_ideate_kind_filter(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, kind="permutation"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "permutation ideas" in out.lower()


def test_ideate_actions_draft_plan(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, actions=True, draft=True, top=3))
    assert rc == 0
    # Action-plan markdown is rendered instead of the raw idea tree.
    assert capsys.readouterr().out.strip()


def test_ideate_writes_out_file(tmp_path, capsys):
    _project(tmp_path)
    out_file = tmp_path / "ideas.md"
    rc = cmd_ideate(_ideate_ns(tmp_path, out=str(out_file)))
    assert rc == 0
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8").strip()


def test_ideate_roadmap_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, roadmap=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Engineering Roadmap" in out
    assert "Phase 1: Stabilize" in out


def test_ideate_roadmap_json(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ideate(_ideate_ns(tmp_path, roadmap=True, json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "phases" in payload
    assert "quick_wins" in payload


def test_ideate_roadmap_writes_out_file(tmp_path):
    _project(tmp_path)
    out_file = tmp_path / "roadmap.md"
    rc = cmd_ideate(_ideate_ns(tmp_path, roadmap=True, out=str(out_file)))
    assert rc == 0
    assert "Engineering Roadmap" in out_file.read_text(encoding="utf-8")


def test_fractal_analyze(tmp_path, capsys):
    _project(tmp_path)
    args = argparse.Namespace(
        subcommand="analyze",
        target=str(tmp_path),
        depth=1,
        max_fractal_budget=2,
        json=False,
    )
    rc = cmd_fractal(args)
    assert rc == 0
    assert "Scanned" in capsys.readouterr().out


def test_fractal_tree(capsys):
    finding = json.dumps(
        {"title": "eval injection", "severity": "high", "file": "app/core.py", "line": 2}
    )
    args = argparse.Namespace(
        subcommand="tree", target="", depth=2, finding=finding, json=False
    )
    rc = cmd_fractal(args)
    assert rc == 0
    assert capsys.readouterr().out.strip()
