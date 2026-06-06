from app.skills.repair.repair_failed_test import RepairFailedTestSkill, RepairSuggestion


def _run(failure_type, patch_plan=None):
    return RepairFailedTestSkill().run({"primary_failure_type": failure_type}, patch_plan)


def test_patch_apply_failure_recommends_input_repair_and_retry():
    s = _run("patch_apply_failure", {"target_files": ["a.py", "b.py"]})
    assert s.repair_type == "patch_input_repair"
    assert s.retry_recommended is True
    assert s.target_files == ["a.py", "b.py"]
    assert any("expected_old_content" in a for a in s.suggested_actions)


def test_test_failure_recommends_regression_and_retry():
    s = _run("test_failure", {"target_files": ["x.py"]})
    assert s.repair_type == "test_failure_repair"
    assert s.retry_recommended is True
    assert any("regression test" in a for a in s.suggested_actions)


def test_patch_scope_failure_caps_target_files_to_three():
    files = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    s = _run("patch_scope_failure", {"target_files": files})
    assert s.repair_type == "scope_reduction"
    assert s.target_files == files[:3]
    assert s.retry_recommended is True


def test_sensitive_edit_requires_review_and_no_retry():
    s = _run("sensitive_edit", {"target_files": ["secrets.py"]})
    assert s.repair_type == "sensitive_review_required"
    assert s.retry_recommended is False
    assert any("manual review" in a.lower() for a in s.suggested_actions)


def test_unknown_failure_type_needs_no_repair():
    s = _run("something_else")
    assert s.repair_type == "no_repair_needed"
    assert s.retry_recommended is False
    assert s.target_files == []


def test_missing_failure_type_defaults_to_no_repair():
    s = RepairFailedTestSkill().run({})
    assert s.repair_type == "no_repair_needed"


def test_none_patch_plan_yields_empty_target_files():
    s = RepairFailedTestSkill().run({"primary_failure_type": "test_failure"}, None)
    assert s.target_files == []


def test_repair_suggestion_to_dict_roundtrips_fields():
    s = RepairSuggestion(
        repair_type="t", suggested_actions=["go"], target_files=["f.py"], retry_recommended=True
    )
    d = s.to_dict()
    assert d == {
        "repair_type": "t",
        "suggested_actions": ["go"],
        "target_files": ["f.py"],
        "retry_recommended": True,
    }
