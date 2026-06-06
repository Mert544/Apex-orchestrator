from pathlib import Path

from app.execution.semantic.generators.draft import fallback_draft


def test_fallback_draft_builds_a_draft_document(tmp_path: Path):
    res = fallback_draft(
        tmp_path, task_id="t-1", title="Do the thing", branch="x.a",
        patch_plan={"change_strategy": ["modernize none-comparison"],
                    "verification_steps": ["run pytest"]},
        reason="no transform matched",
    )
    assert res.transform_type == "draft_fallback"
    assert res.mode == "draft"
    pr = res.patch_requests[0]
    assert pr["path"] == ".apex/patch-drafts/t-1.md"
    assert pr["expected_old_content"] is None
    body = pr["new_content"]
    assert "t-1" in body and "Do the thing" in body and "x.a" in body
    assert "modernize none-comparison" in body and "run pytest" in body
    assert "no transform matched" in " ".join(res.rationale)


def test_fallback_draft_has_defaults_when_plan_empty(tmp_path: Path):
    res = fallback_draft(tmp_path, "t-2", "T", "x.b", {}, "fallback")
    body = res.patch_requests[0]["new_content"]
    assert "No explicit change strategy captured." in body
    assert "Run detected project tests." in body
