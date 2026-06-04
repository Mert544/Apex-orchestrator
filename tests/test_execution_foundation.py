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
    # Self-contained test avoids PYTHONPATH / package import issues.
    _write(root / "tests" / "test_main.py", "def test_add():\n    assert 2 + 3 == 5\n")
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

    import sys
    # pytest is invoked via the current interpreter (robust against a bare
    # `pytest` resolving to a different Python without the project's deps).
    assert result.commands == [[sys.executable, "-m", "pytest", "-q"]]
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


def test_command_runner_allows_interpreter_by_basename():
    # An absolute interpreter path (sys.executable) must be permitted when its
    # basename ("python") is allowlisted — otherwise sys.executable -m pytest is
    # wrongly blocked (this broke autonomous fix verification).
    import sys
    from app.runtime.command_runner import CommandRunner, CommandSpec

    runner = CommandRunner()
    res = runner.run(CommandSpec(command=[sys.executable, "-c", "print('ok')"]))
    assert res.ok and "ok" in res.stdout


def test_command_runner_still_blocks_disallowed_binary():
    import pytest
    from app.runtime.command_runner import CommandPolicyError, CommandRunner, CommandSpec
    with pytest.raises(CommandPolicyError):
        CommandRunner().run(CommandSpec(command=["/usr/bin/curl", "http://x"]))


def test_run_tests_prefers_target_venv(tmp_path):
    # Apex verifies fixes using the TARGET project's own venv when present, so an
    # external project's dependencies resolve (key to developing other projects).
    import os
    from app.skills.execution.run_tests import RunTestsSkill

    vbin = tmp_path / ".venv" / "bin"
    vbin.mkdir(parents=True)
    (vbin / "python").write_text("#!/bin/sh\n")
    os.chmod(vbin / "python", 0o755)
    assert RunTestsSkill()._python_for(tmp_path) == str(vbin / "python")


def test_run_tests_falls_back_to_current_interpreter(tmp_path):
    import sys
    from app.skills.execution.run_tests import RunTestsSkill
    assert RunTestsSkill()._python_for(tmp_path) == sys.executable
