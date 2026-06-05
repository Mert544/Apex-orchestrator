"""Guard the distributable GitHub Action so it can't silently rot.

The composite action lets any external repo adopt Apex as a CI health gate in a
few lines; if its structure or the commands it invokes drift, downstream users'
pipelines break. These checks are deterministic and offline.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ACTION = Path(__file__).resolve().parents[1] / "action.yml"


def _load() -> dict:
    return yaml.safe_load(_ACTION.read_text(encoding="utf-8"))


def test_action_is_a_valid_composite_action():
    a = _load()
    assert a["runs"]["using"] == "composite"
    assert isinstance(a["runs"]["steps"], list) and a["runs"]["steps"]


def test_action_exposes_the_gate_inputs():
    inputs = _load()["inputs"]
    for key in ("target", "min-score", "base", "fail-on-high"):
        assert key in inputs, f"action.yml lost the '{key}' input"


def test_action_invokes_the_real_apex_gate_commands():
    steps = _load()["runs"]["steps"]
    script = "\n".join(s.get("run", "") for s in steps)
    assert "pip install" in script              # installs Apex from the action checkout
    assert "apex grade" in script and "--min-score" in script
    assert "apex review" in script and "--fail-on-high" in script


def test_action_commands_match_real_cli_flags():
    # The flags the action passes must actually exist on the CLI, or every
    # downstream pipeline fails. Assert they are wired in app/cli.py.
    cli = (Path(__file__).resolve().parents[1] / "app" / "cli.py").read_text(encoding="utf-8")
    assert 'dest="min_score"' in cli
    assert 'dest="fail_on_high"' in cli
