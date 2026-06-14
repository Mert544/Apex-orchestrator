"""Outcomes: malformed artifacts, brief_resolved, grader errors, and to_dict shapes."""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.outcomes import (
    CriterionResult,
    OutcomeReport,
    evaluate,
    load_rubric,
)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def _save_brief(root: Path, branch: str, subject: str, evidence: dict) -> None:
    p = root / ".apex" / "briefs" / f"{branch.replace('/', '_')}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"title": "T", "subject": subject, "evidence": evidence}), encoding="utf-8")


# --- malformed artifacts: error branches return None / vacuous pass ----------

def test_load_rubric_returns_none_on_malformed_json(tmp_path):
    _project(tmp_path)
    rubric = tmp_path / ".apex" / "outcomes.json"
    rubric.parent.mkdir(parents=True, exist_ok=True)
    rubric.write_text("{not json", encoding="utf-8")
    assert load_rubric(tmp_path) is None


def test_load_rubric_returns_none_when_absent(tmp_path):
    _project(tmp_path)
    assert load_rubric(tmp_path) is None


def test_evaluate_returns_none_without_a_rubric(tmp_path):
    _project(tmp_path)
    assert evaluate(tmp_path) is None


def test_malformed_proof_artifact_is_treated_as_absent(tmp_path):
    # _last_proof swallows the JSON error -> the proof criteria pass vacuously.
    _project(tmp_path)
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("{broken", encoding="utf-8")
    report = evaluate(tmp_path, {"criteria": [
        {"type": "no_rollbacks"}, {"type": "no_blind_applies"}]})
    assert report.passed
    assert all("vacuously" in c.detail for c in report.criteria)


# --- brief_resolved grader ----------------------------------------------------

def test_brief_resolved_missing_brief_points_to_save(tmp_path):
    _project(tmp_path)
    report = evaluate(tmp_path, {"criteria": [
        {"type": "brief_resolved", "value": "1.0"}]})
    crit = report.criteria[0]
    assert not crit.passed
    assert "no saved brief" in crit.detail
    assert "--save" in crit.gap


def test_brief_resolved_passes_when_all_items_resolved(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    # "edge case" evidence is gone on this trivial source -> resolved.
    _save_brief(tmp_path, "1.0", "app/m.py", {"edge case": [["app/m.py", 1, "x"]]})
    report = evaluate(tmp_path, {"criteria": [
        {"type": "brief_resolved", "value": "1.0"}]})
    crit = report.criteria[0]
    assert crit.passed
    assert "1/1" in crit.detail


def test_brief_resolved_fails_with_open_items(tmp_path):
    _project(tmp_path)
    # A 12-branch function keeps the "edge case" concern measurably open.
    body = "def f(x):\n" + "".join(
        f"    if x == {i}:\n        return {i}\n" for i in range(12))
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    _save_brief(tmp_path, "1.0", "app/m.py", {"edge case": [["app/m.py", 1, "x"]]})
    report = evaluate(tmp_path, {"criteria": [
        {"type": "brief_resolved", "value": "1.0"}]})
    crit = report.criteria[0]
    assert not crit.passed
    assert "0/1" in crit.detail
    assert "--check" in crit.gap


# --- grader exception path ----------------------------------------------------

def test_grader_exception_is_captured_as_a_failed_criterion(tmp_path):
    _project(tmp_path)
    # arch_layers iterates value as a list; a non-iterable raises inside the
    # grader, which evaluate() must capture as a failed criterion (not crash).
    report = evaluate(tmp_path, {"criteria": [
        {"type": "arch_layers", "value": 5}]})
    assert not report.passed
    crit = report.criteria[0]
    assert crit.type == "arch_layers"
    assert "grader error" in crit.detail
    assert crit.gap


def test_arch_layers_ignores_modules_outside_declared_layers(tmp_path):
    # An edge whose endpoint is in no declared layer is skipped (layer_of -> None),
    # so the contract still holds across the layers we DID name.
    for pkg in ("core", "tools", "extra"):
        (tmp_path / pkg).mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools" / "util.py").write_text(
        "def u():\n    return 1\n", encoding="utf-8")
    (tmp_path / "core" / "svc.py").write_text(
        "from tools.util import u\n\ndef s():\n    return u()\n", encoding="utf-8")
    # `extra` is not in the layer list -> its import edge is ignored, not a violation.
    (tmp_path / "extra" / "x.py").write_text(
        "from tools.util import u\n\ndef x():\n    return u()\n", encoding="utf-8")
    report = evaluate(tmp_path, {"criteria": [
        {"type": "arch_layers", "value": ["core", "tools"]}]})
    assert report.passed
    assert "layering holds" in report.criteria[0].detail


# --- dataclass to_dict shapes -------------------------------------------------

def test_criterion_result_to_dict_shape():
    c = CriterionResult("t", False, "what is true", gap="what to change")
    assert c.to_dict() == {"type": "t", "passed": False,
                           "detail": "what is true", "gap": "what to change"}


def test_outcome_report_to_dict_nests_criteria():
    report = OutcomeReport(passed=False, criteria=[
        CriterionResult("a", True, "ok"),
        CriterionResult("b", False, "bad", gap="fix it")])
    d = report.to_dict()
    assert d["passed"] is False
    assert [c["type"] for c in d["criteria"]] == ["a", "b"]
    assert d["criteria"][1]["gap"] == "fix it"
