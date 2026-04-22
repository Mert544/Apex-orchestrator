from pathlib import Path

from app.automation.models import AutomationContext
from app.automation.runner import SkillAutomationRunner
from app.automation.skills import build_default_registry
from app.skills.repair.analyze_failure_log import AnalyzeFailureLogSkill


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_demo_project(root: Path) -> None:
    _write(root / "app" / "services" / "order_service.py", "def checkout(total: float) -> float:\n    return total\n")
    _write(root / "tests" / "test_order_service.py", "from app.services.order_service import checkout\n\n\ndef test_checkout():\n    assert checkout(10.0) == 10.0\n")
    _write(root / "README.md", "demo project\n")
    _write(root / "pyproject.toml", "[project]\nname = 'demo-loop'\nversion = '0.0.1'\n")


def _make_context(project_root: Path) -> AutomationContext:
    return AutomationContext(
        project_root=project_root,
        objective="Scan the target project, extract meaningful implementation claims, and continue with constitution-driven fractal questioning.",
        config={
            'max_depth': 2,
            'max_total_nodes': 40,
            'top_k_questions': 2,
            'min_security': 0.8,
            'min_quality': 0.6,
            'min_novelty': 0.2,
        },
    )


def test_failure_analysis_detects_scope_failure():
    verification = {
        "test_summary": {"ok": True, "results": []},
        "patch_scope": {
            "ok": False,
            "reasons": ["Patch scope too large: 7 files changed, max allowed is 5."],
        },
        "sensitive_edit": {"ok": True, "touched_sensitive_paths": []},
        "patch_apply": {"ok": True},
    }

    result = AnalyzeFailureLogSkill().run(verification).to_dict()

    assert result["primary_failure_type"] == "patch_scope_failure"
    assert "Reduce the changed file set" in result["recommended_next_step"]


def test_failure_analysis_detects_patch_apply_failure():
    verification = {
        "test_summary": {"ok": True, "results": []},
        "patch_scope": {"ok": True, "reasons": []},
        "sensitive_edit": {"ok": True, "touched_sensitive_paths": []},
        "patch_apply": {"ok": False, "error": "No patch_requests provided."},
    }

    result = AnalyzeFailureLogSkill().run(verification).to_dict()

    assert result["primary_failure_type"] == "patch_apply_failure"
    assert "patch input" in result["recommended_next_step"].lower()


def test_supervised_patch_loop_generates_and_applies_patch(tmp_path: Path):
    _build_demo_project(tmp_path)
    runner = SkillAutomationRunner(build_default_registry())
    context = _make_context(tmp_path)

    result = runner.run_plan("supervised_patch_loop", context)

    assert [step.step_name for step in result.steps] == [
        "run_research",
        "plan_tasks",
        "plan_patch",
        "generate_patch_requests",
        "apply_patch",
        "verify_changes",
        "repair_from_verification",
    ]
    assert all(step.status == "ok" for step in result.steps)
    assert result.steps[0].output["estimated_analysis_tokens"] > 0
    assert result.steps[0].output["estimated_response_tokens"] > 0
    assert result.steps[0].output["estimated_total_tokens"] >= result.steps[0].output["estimated_response_tokens"]
    assert result.steps[3].output["patch_requests"]
    assert result.steps[4].output["ok"] is True
    assert result.steps[4].output["changed_files"]
    assert result.final_output["failure_analysis"]["primary_failure_type"] in {
        "no_failure_detected",
        "patch_scope_failure",
        "sensitive_edit",
        "test_failure",
        "patch_apply_failure",
    }
    assert "repair_suggestion" in result.final_output
