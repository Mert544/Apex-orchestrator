from __future__ import annotations

from app.execution.repair_loop import RepairLoop, RepairLoopResult


def test_repair_loop_runs_without_crashing():
    loop = RepairLoop()
    verification = {
        "tests_passed": 0,
        "tests_failed": 1,
        "failures": [{"test": "test_auth", "reason": "AssertionError"}],
    }
    result = loop.run(verification)
    assert isinstance(result, RepairLoopResult)
    assert "failure_analysis" in result.to_dict()
    assert "repair_suggestion" in result.to_dict()


def test_repair_loop_result_to_dict():
    result = RepairLoopResult(
        failure_analysis={"test": "data"},
        repair_suggestion={"action": "add_guard_clause"},
    )
    d = result.to_dict()
    assert d["failure_analysis"] == {"test": "data"}
    assert d["repair_suggestion"]["action"] == "add_guard_clause"
