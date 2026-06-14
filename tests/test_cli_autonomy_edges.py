"""Deterministic edge-path coverage for app/cli_autonomy.py cmd_* dispatch.

Targets the develop / shield / plan / ascend / simulate / evolve commands and
the small pure helpers (_target_score). Heavy/external pieces (the evolution
loop's subprocess verify, the per-test pytest run inside shield --apply) are
monkeypatched; everything else runs the real engine on tiny tmp_path projects
with --no-verify, which never spawns a subprocess. No time/random/order asserts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_autonomy import (
    _target_score,
    cmd_ascend,
    cmd_develop,
    cmd_evolve,
    cmd_plan,
    cmd_shield,
    cmd_simulate,
)


def _ns(**over) -> argparse.Namespace:
    return argparse.Namespace(**over)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(a, b):\n    return a\n")
    return tmp_path


# --------------------------------------------------------------------------- #
# _target_score                                                               #
# --------------------------------------------------------------------------- #
def test_target_score_integer():
    assert _target_score("90") == 90


def test_target_score_letter_grade_floor():
    assert _target_score("A-") == 90
    assert _target_score("b+") == 87  # case-insensitive


def test_target_score_empty_is_none():
    assert _target_score("") is None


def test_target_score_garbage_is_none():
    assert _target_score("not-a-grade") is None


# --------------------------------------------------------------------------- #
# cmd_develop                                                                 #
# --------------------------------------------------------------------------- #
def _dev_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), objective="dead-params", goal="",
                all_objectives=False, grade=False, history=False, from_dream=False,
                playbook=False, apply=False, max_steps=3, no_verify=True,
                fast=True, json=True)
    base.update(over)
    return _ns(**base)


def test_develop_default_objective_json(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["objective"] == "dead-params"


def test_develop_markdown_path(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


def test_develop_unknown_objective_returns_one(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, objective="nonsense-objective"))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert any("unknown objective" in b for b in payload["blocked"])


def test_develop_playbook(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, playbook=True))
    assert rc == 0
    json.loads(capsys.readouterr().out)  # valid JSON archive


def test_develop_history(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, history=True))
    assert rc == 0
    json.loads(capsys.readouterr().out)


def test_develop_all_objectives(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, all_objectives=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(payload, list)


def test_develop_goal_path(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, goal="reduce-debt"))
    assert rc in (0, 1)
    json.loads(capsys.readouterr().out)


def test_develop_from_dream(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, from_dream=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "modules" in payload and "campaigns" in payload


def test_develop_grade_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, grade=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


def test_develop_all_objectives_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, all_objectives=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


def test_develop_from_dream_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, from_dream=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


def test_develop_playbook_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, playbook=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


def test_develop_history_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_develop(_dev_ns(tmp_path, history=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


# --------------------------------------------------------------------------- #
# cmd_plan                                                                    #
# --------------------------------------------------------------------------- #
def test_plan_json(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_plan(_ns(target=str(tmp_path), goal="", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(payload, list)


def test_plan_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_plan(_ns(target=str(tmp_path), goal="", json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


def test_plan_with_goal_restriction(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_plan(_ns(target=str(tmp_path), goal="reduce-debt", json=True))
    assert rc == 0
    json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------- #
# cmd_ascend                                                                  #
# --------------------------------------------------------------------------- #
def _asc_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), max_rounds=1, until="", apply=False,
                no_verify=True, goal="", max_steps=3, fast=True, json=True)
    base.update(over)
    return _ns(**base)


def test_ascend_dry_run_json(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ascend(_asc_ns(tmp_path))
    assert rc == 0
    json.loads(capsys.readouterr().out)


def test_ascend_dry_run_markdown_hint(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ascend(_asc_ns(tmp_path, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Dry run" in out  # dry-run footer hint


def test_ascend_until_target(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_ascend(_asc_ns(tmp_path, until="A-", json=False))
    assert rc == 0
    assert capsys.readouterr().out.strip()


# --------------------------------------------------------------------------- #
# cmd_simulate                                                                #
# --------------------------------------------------------------------------- #
def test_simulate_json(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_simulate(_ns(target=str(tmp_path), json=True, objective="",
                          max_cycles=1, max_apply=2))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(payload, dict)


def test_simulate_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_simulate(_ns(target=str(tmp_path), json=False, objective="",
                          max_cycles=1, max_apply=2))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


# --------------------------------------------------------------------------- #
# cmd_evolve                                                                  #
# --------------------------------------------------------------------------- #
def _evo_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), objective="", max_cycles=1, max_apply=1,
                mode=None, commit=False, no_verify=True, dry_run=False,
                history=False, json=False, out="")
    base.update(over)
    return _ns(**base)


def test_evolve_history_json(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_evolve(_evo_ns(tmp_path, history=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(payload, list)


def test_evolve_history_markdown(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_evolve(_evo_ns(tmp_path, history=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()


def test_evolve_dry_run(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_evolve(_evo_ns(tmp_path, dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out


def test_evolve_full_loop_monkeypatched(tmp_path, capsys, monkeypatch):
    """The real loop's per-cycle verify spawns pytest; stub the loop + sinks so
    the markdown/record/out branches run deterministically and fast."""
    _project(tmp_path)

    class _FakeResult:
        def to_dict(self):
            return {"cycles": 0, "applied": 0}

    captured = {}

    class _FakeLoop:
        def __init__(self, **kw):
            captured.update(kw)

        def run(self):
            return _FakeResult()

    monkeypatch.setattr("app.engine.evolution.EvolutionLoop", _FakeLoop)
    monkeypatch.setattr("app.engine.evolution.record_run",
                        lambda result, target: None)
    monkeypatch.setattr("app.engine.evolution.render_evolution_markdown",
                        lambda result, target: "# Evolved")

    out_file = tmp_path / "evo.md"
    rc = cmd_evolve(_evo_ns(tmp_path, out=str(out_file)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "# Evolved" in out
    assert out_file.exists()
    # mode defaults to supervised without --commit
    assert captured["mode"] == "supervised"


def test_evolve_full_loop_json_monkeypatched(tmp_path, capsys, monkeypatch):
    _project(tmp_path)

    class _FakeResult:
        def to_dict(self):
            return {"cycles": 1, "applied": 2}

    class _FakeLoop:
        def __init__(self, **kw):
            self.commit = kw.get("commit")

        def run(self):
            return _FakeResult()

    monkeypatch.setattr("app.engine.evolution.EvolutionLoop", _FakeLoop)
    monkeypatch.setattr("app.engine.evolution.record_run",
                        lambda result, target: None)
    monkeypatch.setattr("app.engine.evolution.render_evolution_markdown",
                        lambda result, target: "# Evolved")

    rc = cmd_evolve(_evo_ns(tmp_path, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload == {"cycles": 1, "applied": 2}


# --------------------------------------------------------------------------- #
# cmd_shield                                                                  #
# --------------------------------------------------------------------------- #
def _shield_ns(tmp_path, **over):
    base = dict(target=str(tmp_path), module="", all_modules=False,
                apply=False, json=False)
    base.update(over)
    return _ns(**base)


def test_shield_no_module_no_all_is_usage_error(tmp_path, capsys):
    _project(tmp_path)
    rc = cmd_shield(_shield_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1
    assert "needs a MODULE" in out


def test_shield_module_preview(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pub.py").write_text("def pub(a):\n    return a + 1\n")
    rc = cmd_shield(_shield_ns(tmp_path, module="app/pub.py"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Preview only" in out


def test_shield_module_json(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pub.py").write_text("def pub(a):\n    return a + 1\n")
    rc = cmd_shield(_shield_ns(tmp_path, module="app/pub.py", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["module"]
    assert "content" in payload


def test_shield_module_apply_writes_file(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pub.py").write_text("def pub(a):\n    return a + 1\n")
    rc = cmd_shield(_shield_ns(tmp_path, module="app/pub.py", apply=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Wrote" in out


def test_shield_no_test_built_for_module(tmp_path, capsys):
    # A module that already has a test yields no new shield -> friendly note.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "covered.py").write_text("def f(a):\n    return a\n")
    (tmp_path / "tests" / "test_covered.py").write_text(
        "from app.covered import f\ndef test_f():\n    assert f(1) == 1\n"
    )
    rc = cmd_shield(_shield_ns(tmp_path, module="app/covered.py"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "No test built" in out


def test_shield_all_preview(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pub.py").write_text("def pub(a):\n    return a + 1\n")
    rc = cmd_shield(_shield_ns(tmp_path, all_modules=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "would build" in out or "already has a test" in out


def test_shield_all_json(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pub.py").write_text("def pub(a):\n    return a + 1\n")
    rc = cmd_shield(_shield_ns(tmp_path, all_modules=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(payload) >= {"candidates", "built", "failed", "applied"}


def test_shield_all_apply_verifies_each(tmp_path, capsys, monkeypatch):
    """--all --apply writes each shield then runs it; stub the verify so no
    pytest subprocess runs. Verified -> kept and listed as built."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pub.py").write_text("def pub(a):\n    return a + 1\n")
    monkeypatch.setattr("app.cli_autonomy._verify_one_test",
                        lambda target, path, timeout=120: True)
    rc = cmd_shield(_shield_ns(tmp_path, all_modules=True, apply=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is True
    assert payload["built"]


def test_shield_all_apply_removes_failing(tmp_path, capsys, monkeypatch):
    """A generated test that does not pass is removed (never ship red)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pub.py").write_text("def pub(a):\n    return a + 1\n")
    monkeypatch.setattr("app.cli_autonomy._verify_one_test",
                        lambda target, path, timeout=120: False)
    rc = cmd_shield(_shield_ns(tmp_path, all_modules=True, apply=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "skipped" in out or "didn't pass" in out


def test_shield_all_nothing_to_shield(tmp_path, capsys):
    # Every own module already has a linked test -> celebratory message.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "covered.py").write_text("def f(a):\n    return a\n")
    (tmp_path / "tests" / "test_covered.py").write_text(
        "from app.covered import f\ndef test_f():\n    assert f(1) == 1\n"
    )
    rc = cmd_shield(_shield_ns(tmp_path, all_modules=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "already has a test" in out or "would build" in out
