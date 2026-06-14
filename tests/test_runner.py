from __future__ import annotations

from pathlib import Path

import pytest

from app.automation.models import AutomationContext, AutomationStep
from app.automation.registry import SkillAutomationRegistry
from app.automation.runner import SkillAutomationRunner, _classify_error


def _context(tmp_path: Path) -> AutomationContext:
    return AutomationContext(
        project_root=tmp_path,
        objective="test objective",
        config={},
    )


class _RecordingPlugins:
    """Minimal stand-in for PluginRegistry: records hook invocations in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run_hook(self, hook_name: str, context: dict) -> dict:
        self.calls.append((hook_name, context))
        return context


class TestRunPlanControlFlow:
    def test_unknown_plan_raises_keyerror(self, tmp_path: Path):
        runner = SkillAutomationRunner(SkillAutomationRegistry(), plans={})
        with pytest.raises(KeyError, match="Unknown automation plan"):
            runner.run_plan("nope", _context(tmp_path))

    def test_successful_step_sets_final_output_and_status_ok(self, tmp_path: Path):
        registry = SkillAutomationRegistry()
        registry.register("profile_project", lambda ctx: {"profiled": True})
        plans = {
            "p": [AutomationStep(name="profile", skill_name="profile_project")]
        }
        runner = SkillAutomationRunner(registry, plans=plans)

        result = runner.run_plan("p", _context(tmp_path))

        assert result.plan_name == "p"
        assert len(result.steps) == 1
        assert result.steps[0].status == "ok"
        assert result.steps[0].output == {"profiled": True}
        assert result.final_output == {"profiled": True}

    def test_skill_exception_records_error_and_breaks(self, tmp_path: Path):
        registry = SkillAutomationRegistry()

        def boom(ctx):
            raise ValueError("bad input")

        registry.register("plan_tasks", boom)
        registry.register("run_tests", lambda ctx: {"ran": True})
        plans = {
            "p": [
                AutomationStep(name="plan", skill_name="plan_tasks"),
                AutomationStep(name="tests", skill_name="run_tests"),
            ]
        }
        runner = SkillAutomationRunner(registry, plans=plans)

        result = runner.run_plan("p", _context(tmp_path))

        # The failing step is recorded, then the loop breaks before run_tests.
        assert len(result.steps) == 1
        assert result.steps[0].status == "error"
        assert result.steps[0].error == "bad input"
        assert result.steps[0].error_type == "validation"


class TestSafetyGate:
    def _safety_plan(self):
        return {
            "p": [
                AutomationStep(
                    name="safety", skill_name="enhanced_safety_check"
                ),
                AutomationStep(name="apply", skill_name="apply_patch"),
            ]
        }

    def test_safety_block_short_circuits_remaining_steps(self, tmp_path: Path):
        registry = SkillAutomationRegistry()
        registry.register("enhanced_safety_check", lambda ctx: {"ok": False})
        applied = []
        registry.register(
            "apply_patch", lambda ctx: applied.append(True) or {"applied": True}
        )
        runner = SkillAutomationRunner(registry, plans=self._safety_plan())

        result = runner.run_plan("p", _context(tmp_path))

        assert result.final_output["blocked"] is True
        assert result.final_output["reason"] == "safety_gate_failed"
        assert result.final_output["details"] == {"ok": False}
        # apply_patch never ran.
        assert applied == []
        assert len(result.steps) == 1
        assert result.steps[0].skill_name == "enhanced_safety_check"

    def test_safety_pass_continues_to_next_step(self, tmp_path: Path):
        registry = SkillAutomationRegistry()
        registry.register("enhanced_safety_check", lambda ctx: {"passed": True})
        registry.register("apply_patch", lambda ctx: {"applied": True})
        runner = SkillAutomationRunner(registry, plans=self._safety_plan())

        result = runner.run_plan("p", _context(tmp_path))

        assert [s.skill_name for s in result.steps] == [
            "enhanced_safety_check",
            "apply_patch",
        ]
        assert result.final_output == {"applied": True}


class TestEvaluateSafetyOutput:
    def _runner(self):
        return SkillAutomationRunner(SkillAutomationRegistry(), plans={})

    def test_none_output_treated_as_pass(self):
        assert self._runner()._evaluate_safety_output(None) is True

    def test_non_dict_output_treated_as_pass(self):
        assert self._runner()._evaluate_safety_output("anything") is True

    def test_ok_true_passes(self):
        assert self._runner()._evaluate_safety_output({"ok": True}) is True

    def test_passed_true_passes(self):
        assert self._runner()._evaluate_safety_output({"passed": True}) is True

    def test_blocked_false_passes(self):
        assert self._runner()._evaluate_safety_output({"blocked": False}) is True

    def test_blocked_true_fails(self):
        assert self._runner()._evaluate_safety_output({"blocked": True}) is False

    def test_empty_dict_fails(self):
        assert self._runner()._evaluate_safety_output({}) is False


class TestHooks:
    def test_hooks_skipped_when_no_plugins(self, tmp_path: Path):
        # _run_hook returns early when plugins is None; the plan still runs.
        registry = SkillAutomationRegistry()
        registry.register("profile_project", lambda ctx: {"ok": True})
        plans = {"p": [AutomationStep(name="x", skill_name="profile_project")]}
        runner = SkillAutomationRunner(registry, plans=plans, plugins=None)

        result = runner.run_plan("p", _context(tmp_path))
        assert result.steps[0].status == "ok"

    def test_scan_hooks_fire_before_and_after(self, tmp_path: Path):
        registry = SkillAutomationRegistry()
        registry.register("profile_project", lambda ctx: {"ok": True})
        plugins = _RecordingPlugins()
        plans = {"p": [AutomationStep(name="x", skill_name="profile_project")]}
        runner = SkillAutomationRunner(registry, plans=plans, plugins=plugins)

        runner.run_plan("p", _context(tmp_path))

        fired = [name for name, _ in plugins.calls]
        assert "before_scan" in fired
        assert "after_scan" in fired
        assert "on_report" in fired
        # before_scan precedes after_scan precedes on_report.
        assert fired.index("before_scan") < fired.index("after_scan")
        assert fired.index("after_scan") < fired.index("on_report")

    def test_before_scan_fires_only_once_across_scan_skills(self, tmp_path: Path):
        registry = SkillAutomationRegistry()
        registry.register("profile_project", lambda ctx: {"ok": True})
        registry.register("decompose_objective", lambda ctx: {"ok": True})
        registry.register("run_research", lambda ctx: {"ok": True})
        plugins = _RecordingPlugins()
        plans = {
            "p": [
                AutomationStep(name="a", skill_name="profile_project"),
                AutomationStep(name="b", skill_name="decompose_objective"),
                AutomationStep(name="c", skill_name="run_research"),
            ]
        }
        runner = SkillAutomationRunner(registry, plans=plans, plugins=plugins)

        runner.run_plan("p", _context(tmp_path))

        fired = [name for name, _ in plugins.calls]
        assert fired.count("before_scan") == 1
        # after_scan only fires once the last scan skill completes.
        assert fired.count("after_scan") == 1

    def test_patch_and_test_hooks_fire(self, tmp_path: Path):
        registry = SkillAutomationRegistry()
        registry.register("apply_patch", lambda ctx: {"applied": True})
        registry.register("run_tests", lambda ctx: {"tested": True})
        plugins = _RecordingPlugins()
        plans = {
            "p": [
                AutomationStep(name="patch", skill_name="apply_patch"),
                AutomationStep(name="test", skill_name="run_tests"),
            ]
        }
        runner = SkillAutomationRunner(registry, plans=plans, plugins=plugins)

        runner.run_plan("p", _context(tmp_path))

        fired = [name for name, _ in plugins.calls]
        assert "before_patch" in fired
        assert "after_patch" in fired
        assert "before_test" in fired
        assert "after_test" in fired
        # after_patch precedes before_test (patch step finishes before test step).
        assert fired.index("after_patch") < fired.index("before_test")


class TestClassifyError:
    def test_validation_errors(self):
        assert _classify_error(ValueError("x")) == "validation"
        assert _classify_error(TypeError("x")) == "validation"
        assert _classify_error(AssertionError("x")) == "validation"
        assert _classify_error(KeyError("x")) == "validation"

    def test_network_errors(self):
        assert _classify_error(ConnectionError("x")) == "network"
        assert _classify_error(TimeoutError("x")) == "network"
        assert _classify_error(OSError("x")) == "network"

    def test_patch_error_by_class_name(self):
        class PatchApplyError(Exception):
            pass

        assert _classify_error(PatchApplyError("boom")) == "patch"

    def test_timeout_by_message(self):
        class CustomError(Exception):
            pass

        assert _classify_error(CustomError("operation timeout exceeded")) == "timeout"

    def test_unknown_fallback(self):
        class WeirdError(Exception):
            pass

        assert _classify_error(WeirdError("something")) == "unknown"
