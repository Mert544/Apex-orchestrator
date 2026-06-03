from __future__ import annotations

import argparse
from pathlib import Path

from app.cli import cmd_simulate
from app.engine.evolution import EvolutionResult
from app.engine.simulation import render_simulation_markdown, simulate_evolution


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    return tmp_path


def test_simulation_leaves_original_untouched(tmp_path):
    _project(tmp_path)
    before = (tmp_path / "app" / "cfg.py").read_text()
    result = simulate_evolution(str(tmp_path), max_cycles=2, max_apply_per_cycle=3)
    assert isinstance(result, EvolutionResult)
    # The real file is NOT modified by a simulation.
    assert (tmp_path / "app" / "cfg.py").read_text() == before
    assert "yaml.load" in (tmp_path / "app" / "cfg.py").read_text()


def test_simulation_predicts_improvement(tmp_path):
    _project(tmp_path)
    result = simulate_evolution(str(tmp_path), max_cycles=2, max_apply_per_cycle=3)
    # On the disposable copy the yaml finding is driven down.
    assert result.after["security_findings"] <= result.before["security_findings"]
    assert result.applied >= 1


def test_simulation_ignores_vcs_and_caches(tmp_path):
    _project(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("junk")
    # Must not crash on .git/__pycache__ and must still produce a result.
    result = simulate_evolution(str(tmp_path), max_cycles=1, max_apply_per_cycle=2)
    assert isinstance(result, EvolutionResult)


def test_render_simulation_markdown(tmp_path):
    _project(tmp_path)
    md = render_simulation_markdown(simulate_evolution(str(tmp_path), max_cycles=1), str(tmp_path))
    assert "simulated improvement" in md
    assert "no files changed" in md
    assert "Predicted before → after" in md


def test_cmd_simulate_changes_nothing(tmp_path, capsys):
    _project(tmp_path)
    before = (tmp_path / "app" / "cfg.py").read_text()
    args = argparse.Namespace(target=str(tmp_path), objective="", max_cycles=1,
                              max_apply=2, json=False)
    assert cmd_simulate(args) == 0
    assert "simulated improvement" in capsys.readouterr().out
    assert (tmp_path / "app" / "cfg.py").read_text() == before


def test_cmd_simulate_json(tmp_path, capsys):
    _project(tmp_path)
    args = argparse.Namespace(target=str(tmp_path), objective="", max_cycles=1,
                              max_apply=2, json=True)
    assert cmd_simulate(args) == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert "before" in payload and "after" in payload
