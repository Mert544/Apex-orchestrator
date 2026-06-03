from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.engine.feedback_loop import FeedbackLoop
from app.engine.planner import Plan, Planner
from app.memory.graph_store import GraphStore
from app.memory.persistent_memory import PersistentMemoryStore
from app.models.enums import ClaimType, NodeStatus, StopReason
from app.models.node import ResearchNode
from app.models.report import FinalReport
from app.policy.learning import LearningPolicy
from app.policy.mode import ApexMode, ModePolicy, SafetyPolicy


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_node(**overrides) -> ResearchNode:
    defaults = dict(
        id="n1",
        claim="Some claim",
        branch_path="x.a",
        claim_type=ClaimType.ARCHITECTURE,
        claim_priority=0.9,
        confidence=0.8,
        risk=0.4,
        status=NodeStatus.EXPANDED,
    )
    defaults.update(overrides)
    return ResearchNode(**defaults)


def _make_report(**overrides) -> FinalReport:
    defaults = dict(
        objective="demo",
        confidence_map={"A claim": 0.8},
        unresolved_questions=["What contradicts A claim?"],
        main_findings=["A claim"],
        recommended_actions=["Do the thing."],
        branch_map={"x.a": "A claim"},
    )
    defaults.update(overrides)
    return FinalReport(**defaults)


# --------------------------------------------------------------------------- #
# PersistentMemoryStore
# --------------------------------------------------------------------------- #
class TestPersistentMemoryStore:
    def test_estimated_bytes_positive(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        size = store.estimated_bytes()
        assert isinstance(size, int)
        assert size > 0

    def test_hydrate_graph_with_none_graph_returns_state(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        state = store.hydrate_graph(None)
        assert state["known_claims"] == []

    def test_load_state_corrupted_file_falls_back_to_default(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        store.memory_dir.mkdir(parents=True, exist_ok=True)
        store.memory_file.write_text("{not valid json", encoding="utf-8")
        state = store.load_state()
        assert state["known_claims"] == []
        assert state["schema_version"] == 1

    def test_load_state_non_dict_json_falls_back_to_default(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        store.memory_dir.mkdir(parents=True, exist_ok=True)
        store.memory_file.write_text("[1, 2, 3]", encoding="utf-8")
        state = store.load_state()
        assert state["known_questions"] == []

    def test_load_state_existing_file_adds_missing_full_report_key(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        store.memory_dir.mkdir(parents=True, exist_ok=True)
        store.memory_file.write_text(json.dumps({"known_claims": ["x"]}), encoding="utf-8")
        state = store.load_state()
        assert state["last_full_report"] == {}
        assert state["known_claims"] == ["x"]

    def test_load_state_uses_cache_on_second_call(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        first = store.load_state()
        second = store.load_state()
        assert first is second

    def test_persist_run_records_stop_reason(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        report = _make_report()
        node = _make_node(status=NodeStatus.STOPPED, stop_reason=StopReason.MAX_DEPTH)
        store.persist_run("demo", report, [node])
        state = store.load_state()
        assert state["branch_history"][0]["stop_reason"] == "max_depth"

    def test_persist_run_focused_does_not_update_full_report(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        report = _make_report(focus_branch="x.a")
        store.persist_run("demo", report, [_make_node()])
        state = store.load_state()
        assert state["last_full_report"] == {}
        assert state["runs"][0]["run_mode"] == "focused"
        assert state["runs"][0]["focus_branch"] == "x.a"

    def test_persist_run_full_updates_full_report(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        report = _make_report()
        store.persist_run("demo", report, [_make_node()])
        state = store.load_state()
        assert state["last_full_report"] != {}
        assert state["runs"][0]["run_mode"] == "full"

    def test_persist_run_caps_runs_at_25(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        for _ in range(30):
            store.persist_run("demo", _make_report(), [_make_node()])
        state = store.load_state()
        assert len(state["runs"]) == 25

    def test_evict_trims_claims_over_max(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path, max_claims=3, max_questions=3)
        state = {"known_claims": ["a", "b", "c", "d", "e"], "known_questions": []}
        out = store._evict(state)
        assert out["known_claims"] == ["c", "d", "e"]

    def test_evict_aggressive_when_oversized(self, tmp_path: Path):
        store = PersistentMemoryStore(
            project_root=tmp_path,
            max_claims=1000,
            max_questions=1000,
            max_state_size_mb=0.0001,
        )
        state = {
            "known_claims": [f"claim-{i}" for i in range(500)],
            "known_questions": [f"q-{i}" for i in range(500)],
            "branch_history": [{"x": i} for i in range(300)],
        }
        out = store._evict(state)
        # Aggressive trimming kicks in and shrinks branch_history to <= 100.
        assert len(out["branch_history"]) <= 100
        assert len(out["known_claims"]) < 500

    def test_dedupe_drops_empty_and_case_insensitive_duplicates(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        result = store._dedupe(["Hello", "  ", "hello", "World", ""])
        assert result == ["Hello", "World"]

    def test_persist_run_hydrates_back_into_graph(self, tmp_path: Path):
        store = PersistentMemoryStore(project_root=tmp_path)
        report = _make_report(
            confidence_map={"Persisted claim": 0.9},
            unresolved_questions=["Persisted question?"],
        )
        store.persist_run("demo", report, [_make_node(claim="Persisted claim")])
        graph = GraphStore()
        store.hydrate_graph(graph)
        assert graph.has_memory_claim("Persisted claim") is True
        assert graph.has_memory_question("Persisted question?") is True


# --------------------------------------------------------------------------- #
# ModePolicy / SafetyPolicy
# --------------------------------------------------------------------------- #
class TestSafetyPolicyYaml:
    def test_from_yaml_existing_file_loads_values(self, tmp_path: Path):
        path = tmp_path / "policy.yaml"
        path.write_text("check_scope: false\nmax_patch_files: 7\n", encoding="utf-8")
        sp = SafetyPolicy.from_yaml(path)
        assert sp.check_scope is False
        assert sp.max_patch_files == 7

    def test_from_yaml_empty_file_uses_defaults(self, tmp_path: Path):
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        sp = SafetyPolicy.from_yaml(path)
        assert sp.check_scope is True


class TestModePolicyFromEnvSafetyPolicy:
    def test_from_env_uses_safety_policy_file(self, tmp_path: Path, monkeypatch):
        path = tmp_path / "sp.yaml"
        path.write_text("max_patch_files: 3\n", encoding="utf-8")
        monkeypatch.setenv("APEX_MODE", "supervised")
        monkeypatch.setenv("APEX_SAFETY_POLICY", str(path))
        monkeypatch.setenv("APEX_AUTO_PATCH", "1")
        policy = ModePolicy.from_env()
        assert policy.safety_policy.max_patch_files == 3
        assert policy.permissions.can_auto_patch is True

    def test_from_env_supervised_auto_patch_flag(self, monkeypatch):
        monkeypatch.setenv("APEX_MODE", "supervised")
        monkeypatch.setenv("APEX_AUTO_PATCH", "yes")
        monkeypatch.delenv("APEX_SAFETY_POLICY", raising=False)
        policy = ModePolicy.from_env()
        assert policy.permissions.can_auto_patch is True


class TestModePolicyCanApplyPatchMore:
    def _auto_policy(self, **sp_kwargs) -> ModePolicy:
        from app.policy.mode import _build_mode_table

        return ModePolicy(
            mode=ApexMode.AUTONOMOUS,
            permissions=_build_mode_table()[ApexMode.AUTONOMOUS],
            safety_policy=SafetyPolicy(**sp_kwargs),
        )

    def test_can_apply_patch_ok_when_clean(self, monkeypatch, tmp_path: Path):
        # Make clean-tree check return clean by stubbing subprocess.
        import subprocess

        class _Result:
            returncode = 0
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        policy = self._auto_policy()
        ok, reason = policy.can_apply_patch(["a.py"])
        assert ok is True
        assert reason == "ok"

    def test_can_apply_patch_blocks_on_dirty_tree(self, monkeypatch):
        import subprocess

        class _Result:
            returncode = 0
            stdout = " M file.py\n?? other.py\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        policy = self._auto_policy()
        ok, reason = policy.can_apply_patch(["a.py"])
        assert ok is False
        assert "unclean" in reason.lower()

    def test_blocked_pattern_blocks_patch(self, monkeypatch):
        import subprocess

        class _Result:
            returncode = 0
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        policy = self._auto_policy(blocked_patterns=[r"secret"])
        ok, reason = policy.can_apply_patch(["config/secret.yaml"])
        assert ok is False
        assert "pattern" in reason.lower()


class TestCheckCleanTree:
    def _policy(self) -> ModePolicy:
        from app.policy.mode import _build_mode_table

        return ModePolicy(
            mode=ApexMode.AUTONOMOUS,
            permissions=_build_mode_table()[ApexMode.AUTONOMOUS],
            safety_policy=SafetyPolicy(),
        )

    def test_clean_tree_clean(self, monkeypatch):
        import subprocess

        class _Result:
            returncode = 0
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        clean, reason = self._policy()._check_clean_tree()
        assert clean is True
        assert reason == "clean"

    def test_clean_tree_dirty(self, monkeypatch):
        import subprocess

        class _Result:
            returncode = 0
            stdout = " M a.py\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        clean, reason = self._policy()._check_clean_tree()
        assert clean is False
        assert "uncommitted" in reason

    def test_clean_tree_git_failure_returncode(self, monkeypatch):
        import subprocess

        class _Result:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        clean, reason = self._policy()._check_clean_tree()
        assert clean is False
        assert "git status failed" in reason

    def test_clean_tree_exception(self, monkeypatch):
        import subprocess

        def _boom(*a, **k):
            raise OSError("no git")

        monkeypatch.setattr(subprocess, "run", _boom)
        clean, reason = self._policy()._check_clean_tree()
        assert clean is False
        assert "git check failed" in reason


class TestShouldBlock:
    def test_should_block_true_for_real_reason(self):
        from app.policy.mode import _build_mode_table

        policy = ModePolicy(
            mode=ApexMode.SUPERVISED,
            permissions=_build_mode_table()[ApexMode.SUPERVISED],
            safety_policy=SafetyPolicy(),
        )
        assert policy.should_block("some failure") is True

    def test_should_block_false_for_ok(self):
        from app.policy.mode import _build_mode_table

        policy = ModePolicy(
            mode=ApexMode.SUPERVISED,
            permissions=_build_mode_table()[ApexMode.SUPERVISED],
            safety_policy=SafetyPolicy(),
        )
        assert policy.should_block("ok") is False
        assert policy.should_block("") is False


# --------------------------------------------------------------------------- #
# Planner / Plan
# --------------------------------------------------------------------------- #
class TestPlanStrategy:
    def test_reset_restarts_strategy_cycle(self):
        plan = Plan(primary="a", fallbacks=["b"])
        assert plan.next_strategy() == "a"
        assert plan.next_strategy() == "b"
        plan.reset()
        assert plan.current_attempt == 0
        assert plan.next_strategy() == "a"


class TestPlannerStrategies:
    def test_plan_os_system(self):
        plan = Planner().plan({"issue": "os.system call", "file": "x.py", "line": 1})
        assert plan.primary == "replace_with_subprocess_run"
        assert "add_command_whitelist" in plan.fallbacks

    def test_plan_missing_docstring(self):
        plan = Planner().plan({"issue": "missing_docstring", "file": "x.py", "line": 1})
        assert plan.primary == "add_docstring"

    def test_plan_default_review(self):
        plan = Planner().plan({"issue": "something unusual", "file": "x.py", "line": 1})
        assert plan.primary == "review"
        assert "escalate" in plan.fallbacks

    def test_plan_learning_policy_skips_finding(self, tmp_path: Path):
        lp = LearningPolicy()
        finding = {"issue": "eval() usage", "file": "auth.py", "line": 5}
        lp.skip_issue_types.add("eval() usage:auth.py:5")
        planner = Planner(FeedbackLoop(log_dir=str(tmp_path)), learning_policy=lp)
        plan = planner.plan(finding)
        assert plan.primary == "skip"
        assert "escalate" in plan.fallbacks

    def test_plan_known_false_positive_pattern(self, tmp_path: Path):
        feedback = FeedbackLoop(log_dir=str(tmp_path))
        # type-level key drives _is_known_false_positive_pattern via avg < -0.3
        for _ in range(3):
            feedback.update("type:eval", 0.5, -0.5, "type_pattern")
        planner = Planner(feedback)
        plan = planner.plan({"issue": "eval: bad", "file": "x.py", "line": 1})
        assert plan.primary == "review"
        assert plan.fallbacks == ["escalate"]

    def test_plan_learning_policy_escalate_adjustment(self, tmp_path: Path):
        lp = LearningPolicy()
        lp.escalated_types.add("eval")
        planner = Planner(FeedbackLoop(log_dir=str(tmp_path)), learning_policy=lp)
        plan = planner.plan({"issue": "eval: bad", "file": "x.py", "line": 1})
        assert plan.primary == "escalate"
        assert "skip" in plan.fallbacks

    def test_plan_learning_policy_preferred_strategy(self, tmp_path: Path):
        lp = LearningPolicy()
        lp.recommended_strategies["eval"] = "custom_fix"
        planner = Planner(FeedbackLoop(log_dir=str(tmp_path)), learning_policy=lp)
        plan = planner.plan({"issue": "eval: bad", "file": "x.py", "line": 1})
        assert plan.primary == "custom_fix"
        assert "escalate" in plan.fallbacks

    def test_extract_issue_type_with_and_without_colon(self):
        planner = Planner()
        assert planner._extract_issue_type("eval: dangerous") == "eval"
        assert planner._extract_issue_type("bare except") == "bare except"

    def test_confidence_boost_positive(self, tmp_path: Path):
        feedback = FeedbackLoop(log_dir=str(tmp_path))
        feedback.update("type:eval", 0.5, 1.0, "type_pattern")
        planner = Planner(feedback)
        assert planner._get_confidence_boost("eval") == pytest.approx(0.1)

    def test_confidence_boost_negative(self, tmp_path: Path):
        feedback = FeedbackLoop(log_dir=str(tmp_path))
        feedback.update("type:eval", 0.5, -0.5, "type_pattern")
        planner = Planner(feedback)
        assert planner._get_confidence_boost("eval") == pytest.approx(-0.1)

    def test_confidence_boost_neutral(self, tmp_path: Path):
        planner = Planner(FeedbackLoop(log_dir=str(tmp_path)))
        assert planner._get_confidence_boost("unseen") == 0.0

    def test_record_action_result_updates_feedback(self, tmp_path: Path):
        feedback = FeedbackLoop(log_dir=str(tmp_path))
        planner = Planner(feedback)
        finding = {"issue": "eval: bad", "file": "x.py", "line": 3}
        planner.record_action_result(finding, success=True)
        node_key = "eval: bad:x.py:3"
        assert any(e.node_key == node_key for e in feedback.entries)
        assert any(e.node_key == "type:eval" for e in feedback.entries)

    def test_record_action_result_failure_negative_score(self, tmp_path: Path):
        feedback = FeedbackLoop(log_dir=str(tmp_path))
        planner = Planner(feedback)
        finding = {"issue": "eval: bad", "file": "x.py", "line": 3}
        planner.record_action_result(finding, success=False)
        scores = [e.feedback_score for e in feedback.entries]
        assert -0.5 in scores
