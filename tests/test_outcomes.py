"""Outcome rubrics: the blind grader reads artifacts against YOUR bar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.engine.outcomes import evaluate, init_rubric, render_outcomes_markdown


def _clean_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text('def f(x):\n    """D."""\n    return x + 1\n')
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import f\ndef test_f():\n    assert f(1) == 2\n")
    return tmp_path


def test_rubric_passes_on_a_clean_project(tmp_path):
    _clean_project(tmp_path)
    init_rubric(tmp_path)
    report = evaluate(tmp_path)
    assert report is not None and report.passed
    md = render_outcomes_markdown(report)
    assert "PASSED" in md and "artifacts only" in md


def test_security_criterion_fails_with_named_gap(tmp_path):
    _clean_project(tmp_path)
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    report = evaluate(tmp_path, {"criteria": [
        {"type": "max_security_modules", "value": 0}]})
    assert not report.passed
    failed = report.criteria[0]
    assert failed.type == "max_security_modules" and not failed.passed
    assert "apex maintain" in failed.gap  # the gap says what to DO


def test_proof_criteria_read_the_artifact(tmp_path):
    _clean_project(tmp_path)
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(json.dumps({
        "totals": {"rolled_back": 1},
        "fixes": [
            {"outcome": "applied", "finding": {"target": "app/blind.py"},
             "verification": {"strength": {"level": "none"}}},
        ]}))
    report = evaluate(tmp_path, {"criteria": [
        {"type": "no_rollbacks"}, {"type": "no_blind_applies"}]})
    assert not report.passed
    by_type = {c.type: c for c in report.criteria}
    assert "failing_tests" in by_type["no_rollbacks"].gap
    assert "app/blind.py" in by_type["no_blind_applies"].detail


def test_proof_criteria_vacuously_pass_without_a_pass(tmp_path):
    _clean_project(tmp_path)
    report = evaluate(tmp_path, {"criteria": [
        {"type": "no_rollbacks"}, {"type": "no_blind_applies"}]})
    assert report.passed
    assert all("vacuously" in c.detail for c in report.criteria)


def test_unknown_criterion_fails_loudly(tmp_path):
    _clean_project(tmp_path)
    report = evaluate(tmp_path, {"criteria": [{"type": "vibes_good"}]})
    assert not report.passed
    assert "supported:" in report.criteria[0].gap


def test_cli_outcomes_init_then_gate(tmp_path, capsys):
    from app.cli import cmd_outcomes

    _clean_project(tmp_path)
    assert cmd_outcomes(argparse.Namespace(
        target=str(tmp_path), init=True, json=False)) == 0
    assert "Starter rubric" in capsys.readouterr().out

    assert cmd_outcomes(argparse.Namespace(
        target=str(tmp_path), init=False, json=False)) == 0  # clean -> passes

    # Introduce a finding -> the gate goes red with exit code 1.
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    rc = cmd_outcomes(argparse.Namespace(target=str(tmp_path), init=False, json=False))
    out = capsys.readouterr().out
    assert rc == 1 and "GAPS REMAIN" in out and "↳ gap:" in out


def test_cli_outcomes_without_rubric_points_to_init(tmp_path, capsys):
    from app.cli import cmd_outcomes

    _clean_project(tmp_path)
    rc = cmd_outcomes(argparse.Namespace(target=str(tmp_path), init=False, json=False))
    assert rc == 1
    assert "--init" in capsys.readouterr().out
