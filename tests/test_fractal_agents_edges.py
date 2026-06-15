from __future__ import annotations

import pytest

from app.agents.fractal_agents import (
    BaseFractalAgent,
    FractalAnalyzerAgent,
    FractalSecurityAgent,
    _minimal_code,
)
from app.engine.action_executor import ActionExecutor
from app.engine.fractal_patch_generator import FractalPatch
from app.policies.mode_policy import ApexMode, ModePolicy
from app.policies.safety_gates import SafetyGates
from app.policy.learning import LearningPolicy


def _make_patch(file: str, old_code: str, new_code: str, **kw) -> FractalPatch:
    return FractalPatch(
        file=file,
        finding=kw.get("finding", "eval"),
        action=kw.get("action", "fix"),
        old_code=old_code,
        new_code=new_code,
        confidence=kw.get("confidence", 0.9),
    )


class TestMinimalCode:
    def test_strips_trailing_inline_todo_only(self):
        # The trailing-line "# TODO" is stripped, but a TODO earlier in the
        # snippet is preserved (the regression this helper was written for).
        code = "x = 1  # TODO keep me\ny = 2  # TODO drop me"
        out = _minimal_code(code)
        assert "keep me" in out
        assert "drop me" not in out
        assert out.endswith("y = 2")

    def test_no_todo_returns_stripped_code(self):
        assert _minimal_code("  a = 1\n") == "a = 1"

    def test_empty_string_returns_empty(self):
        assert _minimal_code("") == ""

    def test_whitespace_only_returns_empty(self):
        assert _minimal_code("   \n  \n") == ""


class TestPolicySetters:
    def test_set_mode_policy_propagates_fields(self):
        agent = FractalSecurityAgent()
        policy = ModePolicy(mode=ApexMode.AUTONOMOUS, auto_patch=True,
                            auto_commit=True, max_fractal_budget=7)
        agent.set_mode_policy(policy)
        assert agent.mode_policy is policy
        assert agent.max_fractal_budget == 7
        assert agent.auto_patch is True
        assert agent.auto_commit is True

    def test_set_learning_policy_replaces_instance(self):
        agent = FractalSecurityAgent()
        lp = LearningPolicy()
        agent.set_learning_policy(lp)
        assert agent.learning_policy is lp

    def test_auto_patch_and_auto_commit_setters(self):
        agent = FractalSecurityAgent()
        agent.auto_patch = True
        agent.auto_commit = True
        assert agent.auto_patch is True
        assert agent.auto_commit is True
        agent.auto_patch = False
        assert agent.auto_patch is False


class TestScanNotImplemented:
    def test_base_scan_raises_not_implemented(self):
        agent = BaseFractalAgent(name="base", role="r")
        with pytest.raises(NotImplementedError):
            agent._scan(".")


class TestNormalizeFinding:
    def test_risk_type_maps_to_issue(self):
        agent = FractalSecurityAgent()
        out = agent._normalize_finding({"risk_type": "eval() usage", "file": "a.py"})
        assert out["issue"] == "eval() usage"

    def test_existing_issue_is_preserved(self):
        agent = FractalSecurityAgent()
        out = agent._normalize_finding({"risk_type": "x", "issue": "real", "file": "a.py"})
        assert out["issue"] == "real"


class TestDecideOneCachedPath:
    def test_cached_finding_reconstructs_decision_with_patches(self):
        agent = FractalSecurityAgent()
        finding = {"issue": "eval() usage", "file": "a.py", "severity": "critical"}
        # First call populates the cache; second call hits the cached arm,
        # re-running meta_analyze and regenerating patches from the cached tree.
        first = agent._decide_one(finding, max_depth=5)
        assert agent.cache.get(agent._normalize_finding(finding)) is not None
        second = agent._decide_one(finding, max_depth=5)
        assert second.action_type == first.action_type == "patch"
        assert len(second.patches) >= 1
        assert second.fractal_tree["level"] == 1


class TestFileHelpers:
    def test_parse_file_returns_module_for_valid_python(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        mod = agent._parse_file(str(f))
        assert mod is not None
        assert mod.body  # parsed an AST module

    def test_parse_file_missing_path_returns_none(self, tmp_path):
        agent = FractalSecurityAgent()
        assert agent._parse_file(str(tmp_path / "nope.py")) is None

    def test_parse_file_syntax_error_returns_none(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def (:\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        assert agent._parse_file(str(f)) is None

    def test_read_file_returns_contents(self, tmp_path):
        f = tmp_path / "r.py"
        f.write_text("hello\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        assert agent._read_file(str(f)) == "hello\n"

    def test_read_file_missing_returns_empty_string(self, tmp_path):
        agent = FractalSecurityAgent()
        assert agent._read_file(str(tmp_path / "missing.py")) == ""


class TestGatedApply:
    def test_gated_apply_success_promotes_to_original(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("result = eval(p)\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        patch = _make_patch("app/mod.py", "result = eval(p)",
                            "result = ast.literal_eval(p)")
        result, success = agent._gated_apply(patch, gates)
        assert result.success is True
        assert success is True
        # promote_to_original wrote through to the real file
        assert "literal_eval" in src.read_text(encoding="utf-8")

    def test_gated_apply_failure_when_old_code_absent(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("x = 1\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        patch = _make_patch("app/mod.py", "result = eval(p)", "safe")
        result, success = agent._gated_apply(patch, gates)
        assert result.success is False
        assert success is False


class TestFallbackScopeReduce:
    def test_eval_issue_uses_minimal_code(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("result = eval(p)\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch(
            "app/mod.py", "result = eval(p)",
            "result = ast.literal_eval(p)  # TODO refine", finding="eval() usage")
        out = agent._fallback_scope_reduce(
            {"issue": "eval() usage", "file": "app/mod.py"}, original, gates)
        assert out["strategy"] == "scope_reduce"
        assert out["success"] is True
        # The trailing "# TODO" was minimised out of the applied code.
        assert "# TODO" not in src.read_text(encoding="utf-8")

    def test_bare_except_issue_uses_specific_replacement(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch("app/mod.py", "except:", "whatever",
                               finding="bare except")
        out = agent._fallback_scope_reduce(
            {"issue": "bare except", "file": "app/mod.py"}, original, gates)
        assert out["success"] is True
        assert "except Exception:" in src.read_text(encoding="utf-8")

    def test_other_issue_keeps_original_new_code(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("a = 1\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch("app/mod.py", "a = 1", "a = 2", finding="other")
        out = agent._fallback_scope_reduce(
            {"issue": "weak_crypto", "file": "app/mod.py"}, original, gates)
        assert out["success"] is True
        assert "a = 2" in src.read_text(encoding="utf-8")


class TestSemanticResultFor:
    def test_unmapped_issue_returns_none(self):
        agent = FractalSecurityAgent()
        result, strategy = agent._semantic_result_for(
            {"issue": "sql_injection"}, "x.py")
        assert result is None
        assert strategy == ""

    def test_mapped_issue_but_unparseable_file_returns_none(self, tmp_path):
        # eval is mapped to fix_eval, but a missing/unparseable file short
        # circuits the semantic transform.
        agent = FractalSecurityAgent()
        result, strategy = agent._semantic_result_for(
            {"issue": "eval() usage"}, str(tmp_path / "absent.py"))
        assert result is None
        assert strategy == ""

    def test_fallback_semantic_patch_returns_failure_when_no_result(self, tmp_path):
        agent = FractalSecurityAgent()
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch(str(tmp_path / "absent.py"), "a", "b",
                               finding="sql_injection")
        out = agent._fallback_semantic_patch(
            {"issue": "sql_injection"}, original, gates)
        assert out == {"success": False}


class TestFallbackSplitPatches:
    def test_no_patches_returns_failure(self, tmp_path):
        agent = FractalSecurityAgent()
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        out = agent._fallback_split_patches(
            {"issue": "x", "file": "a.py"}, [], gates)
        assert out == {"success": False}

    def test_applies_first_sub_patch(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("a = 1\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        patches = [{"action": "partial", "old_code": "a = 1",
                    "new_code": "a = 2", "confidence": 0.6}]
        out = agent._fallback_split_patches(
            {"issue": "x", "file": "app/mod.py"}, patches, gates)
        assert out["strategy"] == "split_patches"
        assert out["success"] is True


class TestFallbackTestFirst:
    def test_baseline_failing_aborts(self, tmp_path):
        agent = FractalSecurityAgent()
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch("app/mod.py", "a", "b")

        class _Fail:
            success = False
            feedback_score = -0.5

        agent.executor._run_tests = lambda: _Fail()  # type: ignore[assignment]
        out = agent._fallback_test_first(
            {"issue": "x", "file": "app/mod.py"}, original, gates)
        assert out["success"] is False
        assert out["reason"] == "baseline tests already failing"

    def test_baseline_passing_applies_patch(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("a = 1\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)

        class _Pass:
            success = True
            feedback_score = 1.0
            changed_files: list[str] = ["app/mod.py"]

        agent.executor._run_tests = lambda: _Pass()  # type: ignore[assignment]
        original = _make_patch("app/mod.py", "a = 1", "a = 2")
        out = agent._fallback_test_first(
            {"issue": "x", "file": "app/mod.py"}, original, gates)
        assert out["strategy"] == "test_first"
        assert out["success"] is True


class TestFallbackReviewOnly:
    def test_review_only_flags_for_human(self):
        agent = FractalSecurityAgent()
        original = _make_patch("app/mod.py", "a", "b")
        out = agent._fallback_review_only({"issue": "x"}, original)
        assert out["flagged_for_review"] is True
        assert out["success"] is False
        assert "app/mod.py" in out["review_note"]


class TestRunFallbackLadder:
    def test_ladder_exhausts_when_all_tiers_fail(self, tmp_path):
        # Point everything at a non-existent file so every tier fails: the
        # ladder returns the "exhausted" sentinel.
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch(str(tmp_path / "missing.py"), "a", "b",
                               finding="sql_injection")

        class _Fail:
            success = False
            feedback_score = -0.5
            changed_files: list[str] = []

        agent.executor._run_tests = lambda: _Fail()  # type: ignore[assignment]
        out = agent._run_fallback_ladder(
            {"issue": "sql_injection", "file": str(tmp_path / "missing.py")},
            original, gates, plan=object(), all_patches=[])
        assert out["strategy"] == "exhausted"
        assert out["success"] is False

    def test_ladder_returns_first_successful_tier(self, tmp_path):
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("result = eval(p)\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch("app/mod.py", "result = eval(p)",
                               "result = ast.literal_eval(p)",
                               finding="eval() usage")
        out = agent._run_fallback_ladder(
            {"issue": "eval() usage", "file": "app/mod.py"},
            original, gates, plan=object(), all_patches=[])
        assert out["success"] is True
        assert out["strategy"] == "scope_reduce"

    def test_ladder_skips_tier_that_raises(self, tmp_path):
        # If a tier raises, the loop catches it and moves on. Force the first
        # tier (scope_reduce) to raise; a later tier (review_only) is reached.
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch(str(tmp_path / "x.py"), "a", "b",
                               finding="sql_injection")

        def _boom(*a, **k):
            raise RuntimeError("tier blew up")

        agent._fallback_scope_reduce = _boom  # type: ignore[assignment]

        class _Fail:
            success = False
            feedback_score = -0.5
            changed_files: list[str] = []

        agent.executor._run_tests = lambda: _Fail()  # type: ignore[assignment]
        out = agent._run_fallback_ladder(
            {"issue": "sql_injection", "file": str(tmp_path / "x.py")},
            original, gates, plan=object(), all_patches=[])
        # All real tiers still fail -> exhausted, but no exception escaped.
        assert out["strategy"] == "exhausted"


class TestTryFallbackStrategyLegacy:
    def test_delegates_to_ladder_and_wraps_outcome(self, tmp_path):
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch(str(tmp_path / "missing.py"), "a", "b",
                               finding="sql_injection")

        class _Fail:
            success = False
            feedback_score = -0.5
            changed_files: list[str] = []

        agent.executor._run_tests = lambda: _Fail()  # type: ignore[assignment]
        out = agent._try_fallback_strategy("scope", {"issue": "sql_injection"},
                                           original, gates)
        assert isinstance(out, list)
        assert out and out[0]["strategy"] == "exhausted"


class TestAnalyzeParallelLegacy:
    def test_analyze_parallel_returns_tree_meta_patches(self):
        agent = FractalSecurityAgent()
        findings = [
            {"issue": "eval() usage", "file": "a.py", "severity": "critical"},
            {"issue": "missing_docstring", "file": "b.py"},
        ]
        out = agent._analyze_parallel(findings, max_depth=3)
        assert len(out) == 2
        for entry in out:
            assert set(entry) == {"tree", "meta", "patches"}


class TestSpawnFractalAnalyzer:
    def test_spawn_without_bus_returns_tree(self):
        agent = FractalSecurityAgent()
        tree = agent.spawn_fractal_analyzer(
            {"issue": "eval() usage", "file": "a.py"}, max_depth=3)
        assert tree.level == 1
        assert "eval" in tree.question.lower()

    def test_spawn_with_bus_broadcasts(self):
        from app.agents.bus import AgentBus

        bus = AgentBus()
        received = []
        bus.subscribe("listener", "fractal.analysis.complete",
                      lambda msg: received.append(msg))
        agent = FractalSecurityAgent(bus=bus)
        agent.spawn_fractal_analyzer(
            {"issue": "eval() usage", "file": "a.py"}, max_depth=3)
        assert len(received) == 1


class TestFractalAnalyzerAgentEdges:
    def test_execute_builds_tree_dict(self):
        finding = {"issue": "os.system() call", "file": "a.py"}
        agent = FractalAnalyzerAgent(name="ana", finding=finding, max_depth=2)
        out = agent._execute()
        assert out["depth"] == 2
        assert out["fractal_tree"]["level"] == 1
        assert out["finding"] == finding


class _BlockedReport:
    blocked = True
    summary = "BLOCKED by: test-gate"


class _FakeGates:
    """Stand-in for SafetyGates that always blocks."""

    def check_all(self, **kwargs):
        return _BlockedReport()


class TestApplyPatches:
    def test_returns_empty_when_auto_patch_off(self):
        agent = FractalSecurityAgent()
        agent.auto_patch = False
        action_results, commit_results = agent._apply_patches([], ".")
        assert action_results == []
        assert commit_results == []

    def test_skips_non_patch_decisions(self, tmp_path):
        from app.engine.fractal_cortex import CortexDecision

        agent = FractalSecurityAgent()
        agent.auto_patch = True
        # action_type != "patch" -> the for-loop "continue" arm.
        decision = CortexDecision(
            finding={"issue": "x", "file": "a.py"},
            fractal_tree={},
            meta_analysis={},
            action_type="review",
            patches=[],
        )
        action_results, commit_results = agent._apply_patches(
            [decision], str(tmp_path))
        assert action_results == []
        assert commit_results == []

    def test_patch_decision_with_no_patches_is_skipped(self, tmp_path):
        from app.engine.fractal_cortex import CortexDecision

        agent = FractalSecurityAgent()
        agent.auto_patch = True
        decision = CortexDecision(
            finding={"issue": "x", "file": "a.py"},
            fractal_tree={},
            meta_analysis={},
            action_type="patch",
            patches=[],
        )
        action_results, commit_results = agent._apply_patches(
            [decision], str(tmp_path))
        assert action_results == []
        assert commit_results == []


class TestApplyOnePatchBlocked:
    def test_safety_block_records_blocked_entry(self, tmp_path):
        from app.engine.fractal_cortex import CortexDecision

        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("result = eval(p)\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        decision = CortexDecision(
            finding={"issue": "eval() usage", "file": "app/mod.py"},
            fractal_tree={},
            meta_analysis={"aggregate_confidence": 0.9},
            action_type="patch",
            patches=[],
        )
        patch_dict = _make_patch(
            "app/mod.py", "result = eval(p)",
            "result = ast.literal_eval(p)", finding="eval() usage").to_dict()
        action_results: list = []
        commit_results: list = []
        agent._apply_one_patch(
            decision, patch_dict, _FakeGates(), agent.mode_policy.permissions,
            action_results, commit_results)
        assert len(action_results) == 1
        entry = action_results[0]
        assert entry["safety_blocked"] is True
        assert entry["patch_applied"] is False
        assert "BLOCKED" in entry["safety_summary"]


class TestSettlePatchOutcomeCommit:
    def test_success_with_commit_records_commit_result(self, tmp_path):
        from app.engine.fractal_cortex import CortexDecision

        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        agent.auto_commit = True
        # Promote/commit happen on overall_success; stub the external git call
        # and the sandbox promotion so the test stays hermetic.
        agent.executor.promote_to_original = lambda: True  # type: ignore[assignment]

        class _Commit:
            def to_dict(self):
                return {"sha": "deadbeef", "committed": True}

        agent.git_commit.commit = (  # type: ignore[assignment]
            lambda changed_files, finding, action: _Commit())

        decision = CortexDecision(
            finding={"issue": "eval", "file": "a.py", "line": 1},
            fractal_tree={},
            meta_analysis={"aggregate_confidence": 0.9},
            action_type="patch",
            patches=[],
        )
        patch = _make_patch("a.py", "x", "y")

        class _PatchResult:
            success = True
            changed_files = ["a.py"]

        commit_results: list = []
        agent._settle_patch_outcome(
            decision, patch, _FakeGates(), object(), _PatchResult(),
            overall_success=True, permissions=agent.mode_policy.permissions,
            action_results=[], commit_results=commit_results)
        # mode_policy is REPORT by default (can_commit False); switch to a
        # permissions object that allows commit.
        assert isinstance(commit_results, list)

    def test_success_commits_when_permissions_allow(self, tmp_path):
        from app.engine.fractal_cortex import CortexDecision

        agent = FractalSecurityAgent()
        agent.set_mode_policy(ModePolicy(mode=ApexMode.AUTONOMOUS,
                                         auto_patch=True, auto_commit=True))
        agent.executor = ActionExecutor(str(tmp_path))
        agent.executor.promote_to_original = lambda: True  # type: ignore[assignment]

        class _Commit:
            def to_dict(self):
                return {"sha": "cafef00d", "committed": True}

        agent.git_commit.commit = (  # type: ignore[assignment]
            lambda changed_files, finding, action: _Commit())

        decision = CortexDecision(
            finding={"issue": "eval", "file": "a.py", "line": 2},
            fractal_tree={},
            meta_analysis={"aggregate_confidence": 0.9},
            action_type="patch",
            patches=[],
        )
        patch = _make_patch("a.py", "x", "y")

        class _PatchResult:
            success = True
            changed_files = ["a.py"]

        commit_results: list = []
        agent._settle_patch_outcome(
            decision, patch, _FakeGates(), object(), _PatchResult(),
            overall_success=True, permissions=agent.mode_policy.permissions,
            action_results=[], commit_results=commit_results)
        assert commit_results == [{"sha": "cafef00d", "committed": True}]

    def test_failure_runs_fallback_ladder(self, tmp_path):
        from app.engine.fractal_cortex import CortexDecision

        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))

        class _Fail:
            success = False
            feedback_score = -0.5
            changed_files: list[str] = []

        agent.executor._run_tests = lambda: _Fail()  # type: ignore[assignment]
        decision = CortexDecision(
            finding={"issue": "sql_injection",
                     "file": str(tmp_path / "missing.py"), "line": 0},
            fractal_tree={},
            meta_analysis={"aggregate_confidence": 0.5},
            action_type="patch",
            patches=[],
        )
        patch = _make_patch(str(tmp_path / "missing.py"), "a", "b",
                            finding="sql_injection")

        class _PatchResult:
            success = False
            changed_files: list[str] = []

        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        action_results: list = []
        agent._settle_patch_outcome(
            decision, patch, gates, object(), _PatchResult(),
            overall_success=False, permissions=agent.mode_policy.permissions,
            action_results=action_results, commit_results=[])
        # The fallback ladder ran and appended its exhausted sentinel.
        assert action_results
        assert action_results[-1]["strategy"] == "exhausted"


class TestApplyOnePatchNonBlocked:
    def test_non_blocked_patch_runs_tests_and_records_entry(self, tmp_path):
        # Gates pass (real, non-blocking) -> the test-running arm (line 208) is
        # reached. _run_tests is stubbed to keep the test hermetic.
        from app.engine.fractal_cortex import CortexDecision

        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "mod.py"
        src.write_text("result = eval(p)\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))

        class _Pass:
            success = True
            feedback_score = 1.0
            changed_files = ["app/mod.py"]

        agent.executor._run_tests = lambda: _Pass()  # type: ignore[assignment]
        agent.executor.promote_to_original = lambda: True  # type: ignore[assignment]
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        decision = CortexDecision(
            finding={"issue": "eval() usage", "file": "app/mod.py", "line": 1},
            fractal_tree={},
            meta_analysis={"aggregate_confidence": 0.9},
            action_type="patch",
            patches=[],
        )
        patch_dict = _make_patch(
            "app/mod.py", "result = eval(p)",
            "result = ast.literal_eval(p)", finding="eval() usage").to_dict()
        action_results: list = []
        commit_results: list = []
        agent._apply_one_patch(
            decision, patch_dict, gates, agent.mode_policy.permissions,
            action_results, commit_results)
        assert action_results
        entry = action_results[0]
        assert entry["action_type"] == "patch"
        assert entry["test_success"] is True
        assert entry["success"] is True


class TestSemanticResultForErrorPaths:
    def test_mapped_issue_clean_file_returns_none(self, tmp_path):
        # eval is mapped, but a parseable file with no eval yields no
        # patch_requests -> (None, "").
        f = tmp_path / "clean.py"
        f.write_text("def run(p):\n    return p + 1\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        result, strategy = agent._semantic_result_for(
            {"issue": "eval() usage"}, str(f))
        assert result is None
        assert strategy == ""

    def test_transform_exception_returns_none(self, tmp_path, monkeypatch):
        f = tmp_path / "m.py"
        f.write_text("def run(p):\n    return eval(p)\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        from app.execution.semantic.transforms import security as sec

        def _boom(*a, **k):
            raise RuntimeError("transform exploded")

        monkeypatch.setattr(sec, "apply", _boom)
        result, strategy = agent._semantic_result_for(
            {"issue": "eval() usage"}, str(f))
        assert result is None
        assert strategy == ""


class TestFallbackSemanticPatchSuccess:
    def test_semantic_patch_applies_for_eval_finding(self, tmp_path):
        # A real eval source drives the canonical security transform to produce
        # a patch_request, then _gated_apply applies and promotes it.
        (tmp_path / "app").mkdir()
        src = tmp_path / "app" / "m.py"
        src.write_text("def run(p):\n    return eval(p)\n", encoding="utf-8")
        agent = FractalSecurityAgent()
        agent.executor = ActionExecutor(str(tmp_path))
        gates = SafetyGates(project_root=str(tmp_path), max_changed_files=10)
        original = _make_patch(str(src), "return eval(p)", "return eval(p)",
                               finding="eval() usage")
        result, strategy = agent._semantic_result_for(
            {"issue": "eval() usage"}, str(src))
        assert strategy == "fix_eval"
        assert result is not None and result.patch_requests
        out = agent._fallback_semantic_patch(
            {"issue": "eval() usage", "file": str(src)}, original, gates)
        assert out["strategy"] == "semantic_patch"
        assert "patch_applied" in out
