from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

from app.engine.action_executor import ActionExecutor, ActionResult
from app.engine.checkpoint_manager import CheckpointManager
from app.engine.fractal_cortex import CortexDecision, FractalCortex
from app.engine.fractal_patch_generator import FractalPatch


def _patch(**kw: Any) -> FractalPatch:
    defaults = dict(
        file="m.py",
        finding="eval",
        action="fix",
        old_code="eval(x)",
        new_code="literal_eval(x)",
        confidence=0.9,
    )
    defaults.update(kw)
    return FractalPatch(**defaults)


def _executor(tmp_path: Path, **kw: Any) -> ActionExecutor:
    # The RollbackJournal writes to a cwd-relative ".apex" directory, so tests
    # that touch the journal must chdir into an isolated tmp_path first to avoid
    # picking up the repo's shared journal records.
    (tmp_path / "m.py").write_text("y = eval(x)\n", encoding="utf-8")
    return ActionExecutor(project_root=str(tmp_path), **kw)


# --------------------------------------------------------------------------
# ActionResult / ActionExecutor
# --------------------------------------------------------------------------


class TestActionResult:
    def test_to_dict_round_trips_all_fields(self):
        result = ActionResult(
            action_type="patch",
            success=True,
            stdout="out",
            stderr="err",
            changed_files=["a.py"],
            feedback_score=1.0,
            patch_id="p-1",
        )
        d = result.to_dict()
        assert d == {
            "action_type": "patch",
            "success": True,
            "stdout": "out",
            "stderr": "err",
            "changed_files": ["a.py"],
            "feedback_score": 1.0,
            "patch_id": "p-1",
        }


class TestActionExecutorRunId:
    def test_set_run_id_is_passed_to_journal_record(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ex = _executor(tmp_path)
        ex.set_run_id("run-xyz")
        ex.execute_patch(_patch())
        history = ex.get_patch_history()
        assert history
        assert all(rec["run_id"] == "run-xyz" for rec in history)


class TestExecutePatchRunTests:
    def test_run_tests_success_promotes_score_and_patch_id(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        ex = _executor(tmp_path)

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="1 passed", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = ex.execute_patch(_patch(), run_tests=True)
        assert result.action_type == "test"
        assert result.success is True
        assert result.feedback_score == 1.0
        # patch_id wired through from the recorded patch
        assert result.patch_id
        assert "literal_eval(x)" in (ex.sandbox_dir / "m.py").read_text()

    def test_run_tests_no_tests_collected_is_success(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ex = _executor(tmp_path)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 5, stdout="", stderr=""),
        )
        result = ex.execute_patch(_patch(), run_tests=True)
        assert result.success is True
        assert result.feedback_score == 1.0

    def test_run_tests_failure_gives_negative_score(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ex = _executor(tmp_path)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="boom"
            ),
        )
        result = ex.execute_patch(_patch(), run_tests=True)
        assert result.success is False
        assert result.feedback_score == -0.5
        assert result.stderr == "boom"

    def test_run_tests_subprocess_exception_handled(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ex = _executor(tmp_path)

        def boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 60)

        monkeypatch.setattr(subprocess, "run", boom)
        result = ex.execute_patch(_patch(), run_tests=True)
        assert result.success is False
        assert result.feedback_score == -0.5
        assert result.action_type == "test"

    def test_run_tests_without_sandbox_returns_no_sandbox(self):
        ex = ActionExecutor(project_root=".", enable_rollback=False)
        # _run_tests guards against a missing sandbox directly.
        result = ex._run_tests()
        assert result.success is False
        assert result.stderr == "No sandbox"


class TestPromoteAndRollback:
    def test_promote_without_sandbox_returns_false(self):
        ex = ActionExecutor(project_root=".", enable_rollback=False)
        assert ex.promote_to_original() is False

    def test_promote_restores_exact_content_and_marks_promoted(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        original = "y = eval(x)\n"
        (tmp_path / "m.py").write_text(original, encoding="utf-8")
        ex = ActionExecutor(project_root=str(tmp_path))
        ex.execute_patch(_patch())
        assert ex.promote_to_original() is True
        promoted = (tmp_path / "m.py").read_text()
        assert promoted == "y = literal_eval(x)\n"
        history = ex.get_patch_history()
        assert any(rec["promoted"] for rec in history)

    def test_rollback_last_restores_exact_original(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        original = "y = eval(x)\n"
        (tmp_path / "m.py").write_text(original, encoding="utf-8")
        ex = ActionExecutor(project_root=str(tmp_path))
        ex.execute_patch(_patch())
        ex.promote_to_original()
        assert (tmp_path / "m.py").read_text() != original
        assert ex.rollback_last() is True
        assert (tmp_path / "m.py").read_text() == original

    def test_rollback_all_counts_reverted_patches(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        original = "y = eval(x)\n"
        (tmp_path / "m.py").write_text(original, encoding="utf-8")
        ex = ActionExecutor(project_root=str(tmp_path))
        ex.execute_patch(_patch())
        ex.promote_to_original()
        assert ex.rollback_all() == 1
        assert (tmp_path / "m.py").read_text() == original

    def test_rollback_file_restores_specific_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        original = "y = eval(x)\n"
        (tmp_path / "m.py").write_text(original, encoding="utf-8")
        ex = ActionExecutor(project_root=str(tmp_path))
        ex.execute_patch(_patch())
        ex.promote_to_original()
        assert ex.rollback_file("m.py") is True
        assert (tmp_path / "m.py").read_text() == original

    def test_rollback_file_unknown_returns_false(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ex = _executor(tmp_path)
        ex.execute_patch(_patch())
        assert ex.rollback_file("nope.py") is False

    def test_rollback_methods_no_journal_are_noops(self):
        ex = ActionExecutor(project_root=".", enable_rollback=False)
        assert ex.rollback_last() is False
        assert ex.rollback_all() == 0
        assert ex.rollback_file("x.py") is False
        assert ex.get_patch_history() == []


# --------------------------------------------------------------------------
# CheckpointManager
# --------------------------------------------------------------------------


def _mgr(tmp_path: Path) -> CheckpointManager:
    return CheckpointManager(project_root=str(tmp_path))


class TestCheckpointGitCommit:
    def test_git_commit_invoked_when_changes_present(self, tmp_path: Path, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=" M file\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        m = _mgr(tmp_path)
        m.save_checkpoint("r1", "supervised", "fix", force=True)
        commands = [c[:3] for c in calls]
        assert ["git", "status", "--porcelain"] in commands
        assert any(c[:2] == ["git", "add"] for c in calls)
        assert any("commit" in c for c in calls)

    def test_git_commit_skipped_when_clean(self, tmp_path: Path, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        m = _mgr(tmp_path)
        m.save_checkpoint("r2", "supervised", "fix", force=True)
        # Only the status check runs; nothing is added or committed.
        assert all(c[:2] != ["git", "add"] for c in calls)

    def test_git_commit_swallows_exceptions(self, tmp_path: Path, monkeypatch):
        def boom(cmd, **kwargs):
            raise FileNotFoundError("no git")

        monkeypatch.setattr(subprocess, "run", boom)
        m = _mgr(tmp_path)
        # Must not raise even though git is unavailable.
        result = m.save_checkpoint("r3", "supervised", "fix", force=True)
        assert result["saved"] is True


class TestCheckpointCorruptFiles:
    def test_load_latest_corrupt_returns_none(self, tmp_path: Path):
        m = _mgr(tmp_path)
        (m.checkpoint_dir / "latest.json").write_text("{not json", encoding="utf-8")
        assert m.load_latest_checkpoint() is None

    def test_list_checkpoints_skips_corrupt(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        m = _mgr(tmp_path)
        m.save_checkpoint("good", "report", "g", force=True)
        (m.checkpoint_dir / "checkpoint-bad.json").write_text("broken", encoding="utf-8")
        results = m.list_checkpoints()
        ids = {c["run_id"] for c in results}
        assert "good" in ids
        # The corrupt file is silently skipped, not surfaced.
        assert all("run_id" in c for c in results)

    def test_list_checkpoints_honors_limit(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        m = _mgr(tmp_path)
        for i in range(3):
            m.save_checkpoint(f"r{i}", "report", "g", force=True)
        assert len(m.list_checkpoints(limit=2)) == 2

    def test_get_checkpoint_corrupt_returns_none(self, tmp_path: Path):
        m = _mgr(tmp_path)
        (m.checkpoint_dir / "checkpoint-bad.json").write_text(
            "{oops", encoding="utf-8"
        )
        assert m.get_checkpoint("bad") is None

    def test_saved_checkpoint_is_valid_json_with_expected_fields(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        m = _mgr(tmp_path)
        m.save_checkpoint("r9", "supervised", "do the thing", force=True)
        raw = (m.checkpoint_dir / "checkpoint-r9.json").read_text()
        data = json.loads(raw)
        assert data["run_id"] == "r9"
        assert data["mode"] == "supervised"
        assert data["goal"] == "do the thing"
        assert "timestamp" in data
        assert data["stats"] == {}


# --------------------------------------------------------------------------
# FractalCortex
# --------------------------------------------------------------------------


class _FakeSemanticResult:
    def __init__(self, patch_requests, transform_type="add_docstring"):
        self.patch_requests = patch_requests
        self.transform_type = transform_type


class TestCortexDecision:
    def test_to_dict_round_trips_all_fields(self):
        decision = CortexDecision(
            finding={"issue": "eval"},
            fractal_tree={"level": 1},
            meta_analysis={"recommended_action": "patch"},
            action_type="patch",
            patches=[{"file": "a.py"}],
            rationale="because",
            patch_source="semantic",
        )
        d = decision.to_dict()
        assert d["finding"] == {"issue": "eval"}
        assert d["fractal_tree"] == {"level": 1}
        assert d["action_type"] == "patch"
        assert d["patches"] == [{"file": "a.py"}]
        assert d["rationale"] == "because"
        assert d["patch_source"] == "semantic"


class TestCortexSemanticPath:
    def test_semantic_patches_used_when_generator_returns_requests(self, monkeypatch):
        cortex = FractalCortex(max_depth=3)
        fake = _FakeSemanticResult(
            patch_requests=[
                {
                    "expected_old_content": "def f():",
                    "new_content": 'def f():\n    """doc."""',
                }
            ],
            transform_type="add_docstring",
        )
        monkeypatch.setattr(
            cortex.semantic_patch_generator, "generate", lambda **kw: fake
        )
        finding = {"issue": "eval() usage", "file": "auth.py", "severity": "critical"}
        decision = cortex.decide(finding)
        assert decision.action_type == "patch"
        assert decision.patch_source == "semantic"
        assert len(decision.patches) == 1
        patch = decision.patches[0]
        assert patch["old_code"] == "def f():"
        assert patch["new_code"] == 'def f():\n    """doc."""'
        assert patch["confidence"] == 0.9
        assert patch["patch_source"] == "semantic"
        # The converted new_code must be parseable Python.
        ast.parse(patch["new_code"])

    def test_falls_back_to_fractal_when_semantic_empty(self, monkeypatch):
        cortex = FractalCortex(max_depth=3)
        empty = _FakeSemanticResult(patch_requests=[], transform_type="none")
        monkeypatch.setattr(
            cortex.semantic_patch_generator, "generate", lambda **kw: empty
        )
        finding = {"issue": "eval() usage", "file": "auth.py", "severity": "critical"}
        decision = cortex.decide(finding)
        assert decision.patch_source == "fractal"
        assert len(decision.patches) >= 1

    def test_semantic_generator_exception_falls_back_to_fractal(self, monkeypatch):
        cortex = FractalCortex(max_depth=3)

        def boom(**kw):
            raise RuntimeError("transform failed")

        monkeypatch.setattr(cortex.semantic_patch_generator, "generate", boom)
        finding = {"issue": "eval() usage", "file": "auth.py", "severity": "critical"}
        decision = cortex.decide(finding)
        assert decision.patch_source == "fractal"
        assert len(decision.patches) >= 1

    def test_use_semantic_false_skips_semantic_generator(self):
        cortex = FractalCortex(max_depth=3, use_semantic=False)
        assert not hasattr(cortex, "semantic_patch_generator")
        finding = {"issue": "eval() usage", "file": "auth.py", "severity": "critical"}
        decision = cortex.decide(finding)
        assert decision.patch_source == "fractal"
        assert len(decision.patches) >= 1

    def test_transform_type_none_yields_lower_confidence(self):
        cortex = FractalCortex(max_depth=3)
        fake = _FakeSemanticResult(
            patch_requests=[{"expected_old_content": "a", "new_content": "b"}],
            transform_type="none",
        )
        finding = {"issue": "eval() usage", "file": "x.py"}
        patches = cortex._convert_semantic_to_fractal_patches(fake, finding)
        assert patches[0]["confidence"] == 0.5


class TestCortexGenerateSemanticPatch:
    def _meta(self) -> dict[str, Any]:
        return {"recommended_action": "patch"}

    def test_strategy_mapping_for_known_issues(self, monkeypatch):
        cortex = FractalCortex(max_depth=3)
        captured: dict[str, Any] = {}

        def capture(**kw):
            captured["plan"] = kw["patch_plan"]
            return _FakeSemanticResult(patch_requests=[])

        monkeypatch.setattr(cortex.semantic_patch_generator, "generate", capture)

        cases = {
            "eval is bad": "fix_eval",
            "os.system call": "fix_os_system",
            "bare except found": "fix_bare_except",
            "missing_docstring here": "add_docstring",
            "missing_test for f": "repair_test",
        }
        for issue, expected_strategy in cases.items():
            finding = {"issue": issue, "file": "x.py", "line": 7}
            cortex._generate_semantic_patch(finding, self._meta())
            assert captured["plan"]["strategy"] == expected_strategy
            assert captured["plan"]["target_files"] == ["x.py"]
            assert captured["plan"]["targets"] == [{"path": "x.py", "type": "file"}]
            assert captured["plan"]["task_id"] == "fractal-7"

    def test_unknown_issue_returns_none_without_calling_generator(self, monkeypatch):
        cortex = FractalCortex(max_depth=3)

        def fail(**kw):
            raise AssertionError("generator should not be called")

        monkeypatch.setattr(cortex.semantic_patch_generator, "generate", fail)
        result = cortex._generate_semantic_patch(
            {"issue": "totally unrelated", "file": "x.py"}, self._meta()
        )
        assert result is None

    def test_generator_exception_returns_none(self, monkeypatch):
        cortex = FractalCortex(max_depth=3)

        def boom(**kw):
            raise ValueError("nope")

        monkeypatch.setattr(cortex.semantic_patch_generator, "generate", boom)
        result = cortex._generate_semantic_patch(
            {"issue": "eval here", "file": "x.py"}, self._meta()
        )
        assert result is None


class TestCortexNonPatchAction:
    def test_non_patch_action_yields_no_patches(self):
        cortex = FractalCortex(max_depth=3)
        # A low-severity informational finding should not be auto-patched.
        finding = {"issue": "style nitpick", "file": "x.py", "severity": "info"}
        decision = cortex.decide(finding)
        if decision.action_type != "patch":
            assert decision.patches == []
            assert decision.patch_source == "fractal"
