from pathlib import Path

from app.automation.models import AutomationContext
from app.automation.runner import SkillAutomationRunner
from app.automation.skills import build_default_registry
from app.skills.execution.run_tests import RunTestsSkill
from app.skills.safety.check_patch_scope import CheckPatchScopeSkill


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_demo_project(root: Path) -> None:
    _write(root / "app" / "main.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(root / "tests" / "test_main.py", "from app.main import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    _write(root / "pyproject.toml", "[project]\nname = 'demo-verify'\nversion = '0.0.1'\n")


def _make_context(project_root: Path) -> AutomationContext:
    return AutomationContext(
        project_root=project_root,
        objective="Verify that the project is testable and structurally analyzable.",
        config={
            'max_depth': 2,
            'max_total_nodes': 20,
            'top_k_questions': 2,
            'min_security': 0.8,
            'min_quality': 0.6,
            'min_novelty': 0.2,
        },
    )


def test_run_tests_skill_executes_pytest_for_python_project(tmp_path: Path):
    _build_demo_project(tmp_path)
    result = RunTestsSkill().run(tmp_path)

    assert result.commands == [["pytest", "-q"]]
    assert result.ok is True
    assert result.results
    assert result.results[0]["ok"] is True


def test_check_patch_scope_flags_sensitive_and_large_changes():
    result = CheckPatchScopeSkill().run(
        changed_files=[
            "app/services/order_service.py",
            "app/auth/token_service.py",
            ".github/workflows/ci.yml",
            "README.md",
            "docs/branding.md",
            "tests/test_main.py",
        ],
        max_allowed_files=3,
    )

    assert result.ok is False
    assert result.changed_file_count == 6
    assert result.touched_sensitive_paths
    assert len(result.reasons) >= 2


def test_verify_project_plan_profiles_and_runs_tests(tmp_path: Path):
    _build_demo_project(tmp_path)
    runner = SkillAutomationRunner(build_default_registry())

    result = runner.run_plan("verify_project", _make_context(tmp_path))

    assert [step.step_name for step in result.steps] == ["profile_project", "run_tests"]
    assert all(step.status == "ok" for step in result.steps)
    assert result.final_output["ok"] is True
