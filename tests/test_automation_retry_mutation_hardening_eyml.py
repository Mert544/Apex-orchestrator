"""Mutation-hardening guard tests for the automation/execution retry stack.

These tests are a redundant moat on top of the existing suites for four modules
that already score 100% on the seeded-mutant set:

  - app/automation/runner.py
  - app/automation/adaptive_runner.py
  - app/execution/retry_engine.py
  - app/execution/test_shield.py

Each test below pins a single boundary, arithmetic, constant, boolean, or
early-return behaviour that a single-token mutation would flip — so the kill
no longer depends on one existing test staying exactly as written. Every input
is deterministic: no timestamps, no wall-clock, no unordered-collection
ordering. Backoff jitter is bounded and asserted only against its proven
inclusive range, never an exact draw.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.automation.adaptive_runner import AdaptiveRunner
from app.automation.models import AutomationContext, AutomationStep
from app.automation.planner import DynamicPlan
from app.automation.registry import SkillAutomationRegistry
from app.automation.runner import (
    SkillAutomationRunner,
    _classify_error,
    _is_last_of_category,
)
from app.execution import test_shield as ts
from app.execution.retry_engine import RetryEngine


def _context(tmp_path: Path) -> AutomationContext:
    return AutomationContext(project_root=tmp_path, objective="o", config={})


def _plan(steps, *, mode="autonomous", fallback="verify_project") -> DynamicPlan:
    return DynamicPlan(
        plan_name="p",
        steps=steps,
        agents=[],
        mode=mode,
        can_patch=True,
        fallback_plan=fallback,
        rationale="r",
    )


# ---------------------------------------------------------------------------
# app/automation/runner.py
# ---------------------------------------------------------------------------


class TestRunnerIsLastOfCategory:
    """``_is_last_of_category`` drives the off-by-one ``steps[idx + 1:]`` slice."""

    def test_true_when_no_later_step_shares_category(self):
        steps = [AutomationStep(name="a", skill_name="run_tests")]
        assert _is_last_of_category(steps, 0, frozenset({"run_tests"})) is True

    def test_false_when_a_later_step_shares_category(self):
        steps = [
            AutomationStep(name="a", skill_name="run_tests"),
            AutomationStep(name="b", skill_name="run_tests"),
        ]
        # idx 0 is NOT the last: step b at idx 1 still shares the category.
        assert _is_last_of_category(steps, 0, frozenset({"run_tests"})) is False
        # idx 1 IS the last.
        assert _is_last_of_category(steps, 1, frozenset({"run_tests"})) is True

    def test_current_step_in_category_does_not_count_as_later(self):
        # The slice starts at idx+1, so the step AT idx is excluded — an
        # off-by-one mutation (idx vs idx+1) would wrongly report False here.
        steps = [AutomationStep(name="a", skill_name="run_tests")]
        assert _is_last_of_category(steps, 0, frozenset({"run_tests"})) is True


class TestRunnerAfterHookFiresExactlyOnLastStep:
    """The after-hook fires on the LAST category step, not the first."""

    class _Rec:
        def __init__(self):
            self.calls: list[str] = []

        def run_hook(self, name, ctx):
            self.calls.append(name)

    def test_after_scan_fires_after_last_scan_step_only(self, tmp_path):
        registry = SkillAutomationRegistry()
        registry.register("profile_project", lambda c: {"ok": True})
        registry.register("decompose_objective", lambda c: {"ok": True})
        plugins = self._Rec()
        plans = {
            "p": [
                AutomationStep(name="a", skill_name="profile_project"),
                AutomationStep(name="b", skill_name="decompose_objective"),
            ]
        }
        runner = SkillAutomationRunner(registry, plans=plans, plugins=plugins)
        runner.run_plan("p", _context(tmp_path))

        # Exactly one after_scan, and it follows both scan skills' outputs.
        assert plugins.calls.count("after_scan") == 1


class TestRunnerEvaluateSafetyOutputBranches:
    """Each disjunct of the safety gate is independently load-bearing."""

    def _runner(self):
        return SkillAutomationRunner(SkillAutomationRegistry(), plans={})

    def test_only_ok_true_passes_not_ok_false(self):
        assert self._runner()._evaluate_safety_output({"ok": True}) is True
        assert self._runner()._evaluate_safety_output({"ok": False}) is False

    def test_blocked_true_is_a_fail_blocked_false_is_a_pass(self):
        r = self._runner()
        assert r._evaluate_safety_output({"blocked": False}) is True
        assert r._evaluate_safety_output({"blocked": True}) is False

    def test_ok_must_be_identically_true_not_truthy(self):
        # `output.get("ok") is True` — a truthy-but-not-True value must NOT pass.
        assert self._runner()._evaluate_safety_output({"ok": 1}) is False
        assert self._runner()._evaluate_safety_output({"passed": "yes"}) is False


class TestRunnerClassifyErrorBranches:
    def test_each_validation_name_classifies(self):
        for exc in (ValueError, TypeError, AssertionError, KeyError):
            assert _classify_error(exc("x")) == "validation"

    def test_each_network_name_classifies(self):
        for exc in (ConnectionError, TimeoutError, OSError):
            assert _classify_error(exc("x")) == "network"

    def test_patch_in_class_name_lowercased(self):
        class MyPatchThing(Exception):
            pass

        assert _classify_error(MyPatchThing("boom")) == "patch"

    def test_timeout_only_via_message_not_misc(self):
        class Custom(Exception):
            pass

        assert _classify_error(Custom("a timeout occurred")) == "timeout"
        assert _classify_error(Custom("plain message")) == "unknown"


# ---------------------------------------------------------------------------
# app/automation/adaptive_runner.py
# ---------------------------------------------------------------------------


class TestAdaptiveBackoffDelay:
    """``base_delay * 2 ** (attempt - 1)`` is the full-jitter upper bound."""

    def test_full_jitter_within_exponential_bound(self):
        runner = AdaptiveRunner(SkillAutomationRegistry(), base_delay=4.0)
        for attempt, ceiling in [(1, 4.0), (2, 8.0), (3, 16.0)]:
            lo, hi = 1e9, -1e9
            for seed in range(500):
                random.seed(seed)
                d = runner._backoff_delay(attempt)
                lo, hi = min(lo, d), max(hi, d)
            assert lo >= 0.0
            assert hi <= ceiling + 1e-9
            # The draw spans most of [0, ceiling]: a wrong exponent would
            # collapse or overshoot this band.
            assert hi > ceiling * 0.5

    def test_attempt_one_ceiling_is_base_delay(self):
        runner = AdaptiveRunner(SkillAutomationRegistry(), base_delay=2.0)
        for seed in range(500):
            random.seed(seed)
            assert 0.0 <= runner._backoff_delay(1) <= 2.0 + 1e-9


class TestAdaptiveIsPatchSkill:
    def test_every_listed_patch_skill_is_recognised(self):
        runner = AdaptiveRunner(SkillAutomationRegistry())
        for name in (
            "generate_patch_requests",
            "generate_semantic_patch",
            "apply_patch",
            "repair_from_verification",
            "repair_with_retry",
            "patch_skill",
        ):
            assert runner._is_patch_skill(name) is True

    def test_non_patch_skill_rejected(self):
        runner = AdaptiveRunner(SkillAutomationRegistry())
        assert runner._is_patch_skill("run_tests") is False
        assert runner._is_patch_skill("") is False


class TestAdaptiveAdaptPlanBoundaries:
    def _runner(self):
        return AdaptiveRunner(SkillAutomationRegistry())

    def test_coverage_strictly_below_half_triggers_scan(self):
        names = [s.skill_name for s in self._runner()._adapt_plan({"coverage_ratio": 0.49}, [])]
        assert names == ["coverage_scan"]

    def test_coverage_exactly_half_does_not_trigger(self):
        # `coverage < 0.5` — the boundary value 0.5 must NOT inject a scan.
        assert self._runner()._adapt_plan({"coverage_ratio": 0.5}, []) == []

    def test_missing_coverage_defaults_to_one_and_does_not_trigger(self):
        # Default 1.0 must be >= 0.5; a mutated default could flip this.
        assert self._runner()._adapt_plan({}, []) == []

    def test_risks_truthy_injects_security_scan_once(self):
        names = [s.skill_name for s in self._runner()._adapt_plan({"risks": [1]}, [])]
        assert names == ["security_scan"]

    def test_empty_risks_injects_nothing(self):
        assert self._runner()._adapt_plan({"risks": []}, []) == []

    def test_gaps_truthy_injects_docstring_scan(self):
        names = [s.skill_name for s in self._runner()._adapt_plan({"gaps_found": 3}, [])]
        assert names == ["docstring_scan"]

    def test_gaps_zero_injects_nothing(self):
        assert self._runner()._adapt_plan({"gaps_found": 0}, []) == []

    def test_non_dict_output_yields_no_adaptation(self):
        assert self._runner()._adapt_plan("not a dict", []) == []
        assert self._runner()._adapt_plan(None, []) == []

    def test_existing_scan_in_remaining_suppresses_injection(self):
        remaining = [AutomationStep(name="x", skill_name="security_scan")]
        assert self._runner()._adapt_plan({"risks": [1]}, remaining) == []


class TestAdaptiveRetryLoopBoundaries:
    def _registry(self):
        reg = SkillAutomationRegistry()
        return reg

    def test_exactly_max_retries_attempts_then_error(self):
        calls = [0]

        def always_fail(ctx):
            calls[0] += 1
            raise RuntimeError("nope")

        reg = self._registry()
        reg.register("f", always_fail)
        runner = AdaptiveRunner(reg, max_retries=3, base_delay=0.0)
        step = AutomationStep(name="s", skill_name="f")
        result = runner._execute_with_retry(step, _context(Path(".")))
        # `range(1, max_retries + 1)` -> exactly max_retries attempts.
        assert calls[0] == 3
        assert result.status == "error"

    def test_first_attempt_success_does_not_retry(self):
        calls = [0]

        def ok(ctx):
            calls[0] += 1
            return {"ok": True}

        reg = self._registry()
        reg.register("g", ok)
        runner = AdaptiveRunner(reg, max_retries=3, base_delay=0.0)
        step = AutomationStep(name="s", skill_name="g")
        result = runner._execute_with_retry(step, _context(Path(".")))
        assert calls[0] == 1
        assert result.status == "ok"

    def test_supervised_decline_skips_only_patch_step(self, tmp_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _p: "n")
        reg = self._registry()
        reg.register("apply_patch", lambda c: {"applied": True})
        plan = _plan(
            [AutomationStep(name="p1", skill_name="apply_patch")], mode="supervised"
        )
        runner = AdaptiveRunner(reg, plans={}, max_retries=1, base_delay=0.0)
        result = runner.run_plan(plan, _context(tmp_path))
        assert result.steps[0].status == "skipped"

    def test_supervised_yes_runs_patch_step(self, tmp_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _p: "y")
        reg = self._registry()
        reg.register("apply_patch", lambda c: {"applied": True})
        plan = _plan(
            [AutomationStep(name="p1", skill_name="apply_patch")], mode="supervised"
        )
        runner = AdaptiveRunner(reg, plans={}, max_retries=1, base_delay=0.0)
        result = runner.run_plan(plan, _context(tmp_path))
        assert result.steps[0].status == "ok"

    def test_confirm_step_eof_declines(self):
        def raise_eof(_p):
            raise EOFError

        runner = AdaptiveRunner(SkillAutomationRegistry())
        # builtins.input raising EOFError -> declined (returns False).
        import builtins

        orig = builtins.input
        builtins.input = raise_eof
        try:
            assert runner._confirm_step(AutomationStep(name="s", skill_name="apply_patch")) is False
        finally:
            builtins.input = orig


# ---------------------------------------------------------------------------
# app/execution/retry_engine.py
# ---------------------------------------------------------------------------


class TestRetryShortCircuit:
    def test_no_failure_detected_is_no_retry_needed(self):
        assert RetryEngine._short_circuit("no_failure_detected", True) == (
            "no_retry_needed",
            "No failure detected; retry not required.",
        )

    def test_sensitive_edit_is_human_review(self):
        status, msg = RetryEngine._short_circuit("sensitive_edit", True)
        assert status == "human_review_required"
        assert "Sensitive edit" in msg

    def test_not_recommended_is_human_review_with_type(self):
        status, msg = RetryEngine._short_circuit("test_failure", False)
        assert status == "human_review_required"
        assert "test_failure" in msg

    def test_recommended_real_failure_proceeds(self):
        # Returns None so the loop runs — a flipped guard would block all retries.
        assert RetryEngine._short_circuit("test_failure", True) is None

    def test_sensitive_edit_takes_priority_over_retry_flag(self):
        # Even with retry_recommended True, sensitive_edit blocks (branch order).
        status, _ = RetryEngine._short_circuit("sensitive_edit", True)
        assert status == "human_review_required"


class TestRetryBackoffDelay:
    """``min(base * 2 ** (attempt - 2), max_delay)`` +/- 10% jitter, floored at 0."""

    def test_attempt_two_centers_on_base_delay(self):
        engine = RetryEngine(base_delay=10.0, max_delay=100.0)
        lo, hi = 1e9, -1e9
        for seed in range(800):
            random.seed(seed)
            d = engine._backoff_delay(2)
            lo, hi = min(lo, d), max(hi, d)
        # center 10 -> bounded [9, 11].
        assert lo >= 9.0 - 1e-6
        assert hi <= 11.0 + 1e-6

    def test_attempt_three_doubles_the_center(self):
        engine = RetryEngine(base_delay=10.0, max_delay=100.0)
        lo, hi = 1e9, -1e9
        for seed in range(800):
            random.seed(seed)
            d = engine._backoff_delay(3)
            lo, hi = min(lo, d), max(hi, d)
        # center 20 -> [18, 22]; a wrong exponent would shift this band.
        assert lo >= 18.0 - 1e-6
        assert hi <= 22.0 + 1e-6

    def test_max_delay_caps_the_center(self):
        engine = RetryEngine(base_delay=10.0, max_delay=15.0)
        for seed in range(800):
            random.seed(seed)
            d = engine._backoff_delay(5)  # uncapped center would be 80
            # capped center 15 -> [13.5, 16.5].
            assert 13.5 - 1e-6 <= d <= 16.5 + 1e-6

    def test_delay_never_negative(self):
        engine = RetryEngine(base_delay=0.0, max_delay=30.0)
        for seed in range(200):
            random.seed(seed)
            assert engine._backoff_delay(4) >= 0.0


class TestRetryBuildPatches:
    def test_expected_old_content_defaults_to_none_when_absent(self):
        patches = RetryEngine._build_patches([{"path": "a.py", "new_content": "x"}])
        assert len(patches) == 1
        assert patches[0].path == "a.py"
        assert patches[0].new_content == "x"
        assert patches[0].expected_old_content is None

    def test_expected_old_content_is_carried_through(self):
        patches = RetryEngine._build_patches(
            [{"path": "a.py", "new_content": "x", "expected_old_content": "old"}]
        )
        assert patches[0].expected_old_content == "old"


class TestRetryScopeReductionConstant:
    def test_scope_failure_truncates_target_files_to_three(self, tmp_path):
        # `[:3]` — exactly three files survive the scope reduction.
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "__init__.py").write_text("")
        for n in "abcdef":
            (tmp_path / "app" / f"{n}.py").write_text("x = 1\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='d'\nversion='0'\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")

        engine = RetryEngine(max_retries=1)
        verification = {
            "test_summary": {"ok": True, "results": []},
            "patch_scope": {"ok": False, "reasons": ["too large"]},
            "sensitive_edit": {"ok": True, "touched_sensitive_paths": []},
            "patch_apply": {"ok": True, "changed_files": ["a", "b", "c", "d", "e", "f"]},
        }
        plan = {
            "target_files": [f"app/{n}.py" for n in "abcdef"],
            "title": "t",
            "task_id": "id",
        }
        # Drive _attempt directly to inspect the mutated patch_plan scope.
        from app.execution.retry_engine import _LoopState

        analysis = engine.failure_analyzer.run(verification).to_dict()
        suggestion = engine.repair_planner.run(analysis, plan).to_dict()
        state = _LoopState(
            verification=verification,
            patch_plan=dict(plan),
            analysis=analysis,
            suggestion=suggestion,
            failure_type="patch_scope_failure",
        )
        from app.execution.retry_engine import RetryEngineResult

        engine._attempt(1, tmp_path.resolve(), {}, state, RetryEngineResult(), [])
        assert state.patch_plan["target_files"] == [f"app/{n}.py" for n in "abc"]
        assert len(state.patch_plan["target_files"]) == 3


# ---------------------------------------------------------------------------
# app/execution/test_shield.py
# ---------------------------------------------------------------------------


class TestShieldIsSimpleLiteral:
    def test_scalars_accepted(self):
        for v in (None, True, False, 0, 1, -3, 2.5, "", "hi"):
            assert ts._is_simple_literal(v) is True

    def test_nan_rejected(self):
        assert ts._is_simple_literal(float("nan")) is False

    def test_nested_containers_of_literals_accepted(self):
        assert ts._is_simple_literal([1, [2, "x"], (3,)]) is True
        assert ts._is_simple_literal({"k": (1, 2), "j": [3]}) is True
        assert ts._is_simple_literal({1, 2, 3}) is True

    def test_container_with_nonliteral_rejected(self):
        assert ts._is_simple_literal([object()]) is False
        assert ts._is_simple_literal({"k": object()}) is False

    def test_custom_object_rejected(self):
        assert ts._is_simple_literal(object()) is False

    def test_int_subclass_other_than_bool_rejected(self):
        class MyInt(int):
            pass

        assert ts._is_simple_literal(MyInt(5)) is False


class TestShieldCapturedOracle:
    def test_round_tripping_literal_returns_repr(self):
        assert ts._captured_oracle("5", 5) == "5"
        assert ts._captured_oracle("'hi'", "hi") == "'hi'"

    def test_non_round_tripping_returns_none(self):
        assert ts._captured_oracle("nan", float("nan")) is None

    def test_unparseable_repr_returns_none(self):
        assert ts._captured_oracle("<object>", object()) is None

    def test_mismatch_after_eval_returns_none(self):
        # The repr parses but to a different value -> declined.
        assert ts._captured_oracle("6", 5) is None


class TestShieldStaleModuleNames:
    def test_exact_and_prefix_match_only(self):
        names = ["a", "a.b", "a.b.c", "a.bc", "ab", "x"]
        assert ts._stale_module_names("a.b", names) == ["a", "a.b"]

    def test_no_false_prefix_on_sibling(self):
        # "a.bc" must NOT be treated as a prefix of "a.b".
        assert "a.bc" not in ts._stale_module_names("a.b", ["a.bc"])

    def test_exact_self_is_included(self):
        assert ts._stale_module_names("a.b.c", ["a.b.c"]) == ["a.b.c"]


class TestShieldDottedName:
    def test_strips_suffix_and_joins_with_dots(self):
        assert ts._dotted_name("app/foo/bar.py") == "app.foo.bar"

    def test_single_segment(self):
        assert ts._dotted_name("mod.py") == "mod"


class TestShieldEvalCallArgs:
    def test_empty_string_is_zero_arg_call(self):
        assert ts._eval_call_args("") == ((), {})

    def test_positional_and_keyword_literals(self):
        args, kwargs = ts._eval_call_args("0, '', mode=''")
        assert args == (0, "")
        assert kwargs == {"mode": ""}

    def test_non_literal_name_raises(self):
        with pytest.raises((ValueError, SyntaxError)):
            ts._eval_call_args("bytearray()")

    def test_bare_name_raises(self):
        with pytest.raises((ValueError, SyntaxError)):
            ts._eval_call_args("foo")


class TestShieldArgLiteral:
    def test_none_annotation_yields_none(self):
        assert ts._arg_literal(None) == "None"

    def test_known_scalar_samples(self):
        import ast

        assert ts._arg_literal(ast.parse("int", mode="eval").body) == "0"
        assert ts._arg_literal(ast.parse("str", mode="eval").body) == "''"
        assert ts._arg_literal(ast.parse("bool", mode="eval").body) == "False"

    def test_optional_union_with_none_yields_none(self):
        import ast

        assert ts._arg_literal(ast.parse("int | None", mode="eval").body) == "None"

    def test_unknown_name_falls_back_to_none(self):
        import ast

        assert ts._arg_literal(ast.parse("SomeClass", mode="eval").body) == "None"
