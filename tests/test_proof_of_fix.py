"""Proof-of-Fix artifact: evidence records for maintenance passes."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from app.engine.proof_of_fix import (
    SCHEMA,
    SCHEMA_VERSION,
    build_proof,
    summarize_test_run,
    write_proof,
)


def _fake_test_summary(stdout: str = "3 passed in 1.20s", ok: bool = True):
    return SimpleNamespace(
        commands=[["python", "-m", "pytest", "-q"]],
        ok=ok,
        results=[{"stdout": stdout, "stderr": "", "duration_seconds": 1.2}],
    )


def test_summarize_parses_pytest_counts():
    ev = summarize_test_run(_fake_test_summary("2 failed, 5 passed in 3.40s", ok=False))
    assert ev["performed"] is True
    assert ev["ok"] is False
    assert ev["tests_passed"] == 5
    assert ev["tests_failed"] == 2
    assert ev["duration_seconds"] == 1.2
    assert ev["commands"] == [["python", "-m", "pytest", "-q"]]


def test_summarize_no_commands_means_not_performed():
    ev = summarize_test_run(SimpleNamespace(commands=[], ok=False, results=[]))
    assert ev["performed"] is False
    assert ev["tests_passed"] == 0


def test_build_proof_classifies_outcomes_and_keeps_totals():
    summary = {
        "mode": "supervised", "verify": True, "commit": False,
        "total_executable": 3, "applied": 1, "rolled_back": 1,
        "blocked": 1, "committed": 0,
        "results": [
            {"branch": "1", "action": "harden_security", "operator": "harden",
             "label": "security-risk", "target": "app/danger.py", "applied": True,
             "transform_type": "fix_eval", "changed_files": ["app/danger.py"],
             "diff": "--- a/app/danger.py\n+++ b/app/danger.py\n",
             "verified": True, "rolled_back": False,
             "test_evidence": {"performed": True, "ok": True, "tests_passed": 3},
             "commit_hash": "abc123", "converged_fixes": 2},
            {"branch": "2", "action": "add_docstring", "operator": "document",
             "label": "dependency-hub", "target": "app/svc.py", "applied": False,
             "rolled_back": True, "reason": "tests failed after patch; changes rolled back",
             "changed_files": ["app/svc.py"]},
            {"branch": "3", "action": "harden_security", "operator": "harden",
             "label": "", "target": "app/x.py", "applied": False,
             "reason": "blocked by safety gates"},
        ],
    }
    proof = build_proof(summary, "/tmp/proj", objective="harden")
    assert proof["schema"] == SCHEMA
    assert proof["schema_version"] == SCHEMA_VERSION
    assert proof["tool"]["name"] == "Apex Orchestrator"
    assert proof["objective"] == "harden"
    assert proof["totals"] == {"executable": 3, "applied": 1, "rolled_back": 1,
                               "blocked": 1, "committed": 0}
    fixes = proof["fixes"]
    assert [f["outcome"] for f in fixes] == ["applied", "rolled_back", "blocked"]
    # The applied fix carries its full evidence chain.
    assert fixes[0]["finding"]["label"] == "security-risk"
    assert fixes[0]["diff"].startswith("--- a/app/danger.py")
    assert fixes[0]["verification"]["tests_passed"] == 3
    assert fixes[0]["commit_hash"] == "abc123"
    assert fixes[0]["converged_fixes"] == 2
    # Rollback evidence keeps the reason; blocked steps say why.
    assert fixes[1]["rollback"] == {"occurred": True,
                                    "reason": "tests failed after patch; changes rolled back"}
    assert fixes[2]["blocked_reason"] == "blocked by safety gates"
    assert fixes[2]["verification"] == {"performed": False}


def test_write_proof_default_path(tmp_path):
    path = write_proof({"schema": SCHEMA}, str(tmp_path))
    assert path == tmp_path / ".apex" / "proof-of-fix.json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == SCHEMA


def test_apply_plan_rows_carry_diff_and_test_evidence(tmp_path):
    # End to end: a real maintenance pass produces rows rich enough to prove.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.idea_permutation import IdeaPermutationEngine

    rep = IdeaPermutationEngine({"max_total_ideas": 20, "max_idea_depth": 1}, tmp_path).run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(rep, project_root=str(tmp_path))
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)
    applied = [r for r in summary["results"] if r.get("applied")]
    assert applied, "expected at least one applied fix"
    fixed = [r for r in applied if "app/danger.py" in (r.get("changed_files") or [])]
    assert fixed and "literal_eval" in fixed[0]["diff"]
    assert fixed[0]["test_evidence"]["performed"] is True
    assert fixed[0]["test_evidence"]["ok"] is True
    assert fixed[0]["test_evidence"]["tests_passed"] >= 1

    proof = build_proof(summary, str(tmp_path))
    record = next(f for f in proof["fixes"] if "app/danger.py" in f["changed_files"])
    assert record["outcome"] == "applied"
    assert "literal_eval" in record["diff"]
    assert record["verification"]["tests_passed"] >= 1


def test_cli_maintain_writes_proof_artifact(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    from app.cli import cmd_maintain

    args = argparse.Namespace(
        target=str(tmp_path), objective="", depth=1, breadth=3, max_ideas=12,
        top=0, mode="supervised", no_verify=False, commit=False, max_apply=0,
        json=True, out="", dry_run=False, proof="",
    )
    rc = cmd_maintain(args)
    assert rc == 0
    # JSON mode keeps stdout machine-parsable; the artifact lands in .apex/.
    json.loads(capsys.readouterr().out)
    proof_file = tmp_path / ".apex" / "proof-of-fix.json"
    assert proof_file.exists()
    proof = json.loads(proof_file.read_text(encoding="utf-8"))
    assert proof["schema"] == SCHEMA
    assert proof["totals"]["applied"] >= 1
    assert any(f["outcome"] == "applied" and f["diff"] for f in proof["fixes"])
