from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from app.cli import cmd_evolve


def _ns(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = dict(
        target=str(tmp_path), objective="", max_cycles=2, max_apply=2, mode=None,
        commit=False, no_verify=False, dry_run=False, history=False, json=False, out="",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _git_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                ["git", "config", "user.name", "t"], ["git", "add", "-A"],
                ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=tmp_path, capture_output=True)
    return tmp_path


def test_evolve_cli_applies_and_reports(tmp_path, capsys):
    _git_project(tmp_path)
    rc = cmd_evolve(_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert "self-improvement run" in out
    assert "Before → After" in out
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()


def test_evolve_cli_dry_run_changes_nothing(tmp_path, capsys):
    _git_project(tmp_path)
    before = (tmp_path / "app" / "cfg.py").read_text()
    rc = cmd_evolve(_ns(tmp_path, dry_run=True))
    assert rc == 0
    assert "dry run" in capsys.readouterr().out.lower()
    assert (tmp_path / "app" / "cfg.py").read_text() == before


def test_evolve_cli_json(tmp_path, capsys):
    _git_project(tmp_path)
    rc = cmd_evolve(_ns(tmp_path, json=True))
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert "before" in payload and "after" in payload and "roadmap_diff" in payload


def test_evolve_cli_records_and_shows_history(tmp_path, capsys):
    _git_project(tmp_path)
    # A real run records an entry...
    cmd_evolve(_ns(tmp_path))
    capsys.readouterr()
    assert (tmp_path / ".apex" / "evolution-history.jsonl").exists()
    # ...and --history reads it back as a trajectory.
    rc = cmd_evolve(_ns(tmp_path, history=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "self-improvement trajectory" in out
    assert "run(s) recorded" in out


def test_evolve_history_empty_when_none(tmp_path, capsys):
    _git_project(tmp_path)
    rc = cmd_evolve(_ns(tmp_path, history=True))
    assert rc == 0
    assert "No evolve runs recorded yet" in capsys.readouterr().out


def test_evolve_cli_writes_out(tmp_path):
    _git_project(tmp_path)
    out_file = tmp_path / "evolve.md"
    rc = cmd_evolve(_ns(tmp_path, out=str(out_file)))
    assert rc == 0
    assert "self-improvement run" in out_file.read_text()
