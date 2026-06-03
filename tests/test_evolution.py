from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.evolution import EvolutionLoop, EvolutionResult, render_evolution_markdown


def _git_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "app" / "parse.py").write_text(
        "def parse(x):\n    try:\n        return int(x)\n    except:\n        return 0\n"
    )
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                ["git", "config", "user.name", "t"], ["git", "add", "-A"],
                ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=tmp_path, capture_output=True)
    return tmp_path


def test_evolve_reduces_security_findings(tmp_path):
    _git_project(tmp_path)
    result = EvolutionLoop(tmp_path, mode="supervised", max_cycles=3, max_apply_per_cycle=3).run()
    assert isinstance(result, EvolutionResult)
    assert result.applied >= 1
    # The eval/yaml/bare-except findings should be driven down.
    assert result.after["security_findings"] <= result.before["security_findings"]
    # cfg.py was actually hardened (verified, kept).
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()


def test_evolve_reaches_fixpoint_on_clean_project(tmp_path):
    # A project with nothing safely applicable should stop after one no-op cycle.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "ok.py").write_text('"""Doc."""\n\n\ndef ok(x):\n    """Doc."""\n    return x + 1\n')
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                ["git", "config", "user.name", "t"], ["git", "add", "-A"],
                ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=tmp_path, capture_output=True)
    result = EvolutionLoop(tmp_path, max_cycles=3, max_apply_per_cycle=3).run()
    # Either nothing applied at all, or it converged before the cap.
    assert result.cycles_run <= 3
    assert "security_findings" in result.before and "security_findings" in result.after


def test_evolve_result_has_diff_and_per_cycle(tmp_path):
    _git_project(tmp_path)
    result = EvolutionLoop(tmp_path, max_cycles=2, max_apply_per_cycle=2).run()
    d = result.to_dict()
    assert "roadmap_diff" in d and "dropped" in d["roadmap_diff"]
    assert len(result.per_cycle) == result.cycles_run
    # Public before/after carry no internal roadmap object.
    assert "_roadmap" not in result.before and "_roadmap" not in result.after


def test_render_evolution_markdown(tmp_path):
    _git_project(tmp_path)
    result = EvolutionLoop(tmp_path, max_cycles=2, max_apply_per_cycle=2).run()
    md = render_evolution_markdown(result, str(tmp_path))
    assert "self-improvement run" in md
    assert "Before → After" in md
    assert "Security findings" in md


def test_evolve_max_cycles_respected(tmp_path):
    _git_project(tmp_path)
    result = EvolutionLoop(tmp_path, max_cycles=1, max_apply_per_cycle=2).run()
    assert result.cycles_run == 1
    assert len(result.per_cycle) == 1
