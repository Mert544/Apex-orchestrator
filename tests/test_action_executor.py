from __future__ import annotations

from pathlib import Path

from app.engine.action_executor import ActionExecutor, ActionResult
from app.engine.fractal_patch_generator import FractalPatch


class TestActionExecutor:
    def test_create_sandbox(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "main.py").write_text("x = 1\n")
        executor = ActionExecutor(str(project))
        sandbox = executor.create_sandbox()
        assert sandbox.exists()
        assert (sandbox / "main.py").exists()
        # Original should be untouched
        assert (project / "main.py").exists()
        executor.cleanup()

    def test_execute_patch(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "main.py").write_text("x = eval(y)\n")
        executor = ActionExecutor(str(project))
        patch = FractalPatch(
            file="main.py",
            finding="eval",
            action="replace",
            old_code="eval(y)",
            new_code="ast.literal_eval(y)",
            confidence=0.9,
        )
        result = executor.execute_patch(patch, run_tests=False)
        assert result.success is True
        assert result.changed_files == ["main.py"]
        # Sandbox should have patch
        sandbox_file = executor.sandbox_dir / "main.py"
        assert "ast.literal_eval" in sandbox_file.read_text()
        # Original should be unchanged
        assert "eval(y)" in (project / "main.py").read_text()
        executor.cleanup()

    def test_promote_to_original(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "main.py").write_text("x = eval(y)\n")
        executor = ActionExecutor(str(project))
        patch = FractalPatch(
            file="main.py",
            finding="eval",
            action="replace",
            old_code="eval(y)",
            new_code="ast.literal_eval(y)",
            confidence=0.9,
        )
        executor.execute_patch(patch, run_tests=False)
        ok = executor.promote_to_original()
        assert ok is True
        assert "ast.literal_eval" in (project / "main.py").read_text()
        executor.cleanup()


class TestActionExecutorEdges:
    def _patch(self, **kw):
        from app.engine.fractal_patch_generator import FractalPatch
        defaults = dict(file="m.py", finding="eval", action="fix",
                        old_code="eval(x)", new_code="literal_eval(x)", confidence=0.9)
        defaults.update(kw)
        return FractalPatch(**defaults)

    def _exec(self, tmp_path):
        from app.engine.action_executor import ActionExecutor
        (tmp_path / "m.py").write_text("y = eval(x)\n")
        return ActionExecutor(project_root=str(tmp_path))

    def test_dry_run_does_not_write(self, tmp_path):
        ex = self._exec(tmp_path)
        result = ex.execute_patch(self._patch(), dry_run=True)
        assert result.success is True
        assert "dry-run" in result.stdout.lower()
        # Sandbox file unchanged.
        assert "eval(x)" in (ex.sandbox_dir / "m.py").read_text()

    def test_file_not_found_in_sandbox(self, tmp_path):
        ex = self._exec(tmp_path)
        result = ex.execute_patch(self._patch(file="missing.py"))
        assert result.success is False
        assert "not found" in result.stderr.lower()

    def test_old_code_not_present(self, tmp_path):
        ex = self._exec(tmp_path)
        result = ex.execute_patch(self._patch(old_code="not_in_file()"))
        assert result.success is False
        assert "old_code" in result.stderr.lower()

    def test_apply_then_rollback_last(self, tmp_path):
        ex = self._exec(tmp_path)
        ex.execute_patch(self._patch())
        assert "literal_eval(x)" in (ex.sandbox_dir / "m.py").read_text()
        # rollback_last restores prior content via the journal.
        ex.rollback_last()

    def test_none_old_code_fails_gracefully(self, tmp_path):
        # A draft/whole-file patch can arrive with old_code=None; it must be
        # rejected with a clear message, not crash on `None in str`.
        ex = self._exec(tmp_path)
        result = ex.execute_patch(self._patch(old_code=None))
        assert result.success is False
        assert "old_code" in result.stderr.lower()
        # Sandbox file is left untouched.
        assert "eval(x)" in (ex.sandbox_dir / "m.py").read_text()


class TestActionResultModel:
    def test_to_dict_round_trips(self):
        r = ActionResult(
            action_type="patch", success=True, stdout="out", stderr="err",
            changed_files=["a.py"], feedback_score=1.0, patch_id="pid",
        )
        assert r.to_dict() == {
            "action_type": "patch",
            "success": True,
            "stdout": "out",
            "stderr": "err",
            "changed_files": ["a.py"],
            "feedback_score": 1.0,
            "patch_id": "pid",
        }


class TestRunTests:
    """execute_patch(run_tests=True) drives the real pytest subprocess."""

    def _project_with_test(self, tmp_path, test_body: str) -> ActionExecutor:
        project = tmp_path / "project"
        project.mkdir()
        (project / "m.py").write_text("y = eval(x)\n")
        (project / "test_sandbox_unit.py").write_text(test_body)
        return ActionExecutor(project_root=str(project))

    def _patch(self):
        return FractalPatch(
            file="m.py", finding="eval", action="fix",
            old_code="eval(x)", new_code="literal_eval(x)", confidence=0.9,
        )

    def test_run_tests_passing_yields_positive_feedback(self, tmp_path):
        ex = self._project_with_test(tmp_path, "def test_ok():\n    assert 1 + 1 == 2\n")
        result = ex.execute_patch(self._patch(), run_tests=True)
        assert result.action_type == "test"
        assert result.success is True
        assert result.feedback_score == 1.0
        # patch_id is threaded through from the apply step (rollback enabled).
        assert result.patch_id
        ex.cleanup()

    def test_run_tests_failing_yields_negative_feedback(self, tmp_path):
        ex = self._project_with_test(tmp_path, "def test_bad():\n    assert False\n")
        result = ex.execute_patch(self._patch(), run_tests=True)
        assert result.success is False
        assert result.feedback_score == -0.5
        ex.cleanup()

    def test_run_tests_no_collected_is_success(self, tmp_path):
        # pytest exit code 5 (no tests collected) is treated as acceptable.
        ex = self._project_with_test(tmp_path, "# nothing to collect\n")
        # Remove the conftest-free empty file content; an empty test module still
        # yields exit code 5 because there are no test functions.
        result = ex.execute_patch(self._patch(), run_tests=True)
        assert result.success is True
        assert result.feedback_score == 1.0
        ex.cleanup()

    def test_run_tests_without_sandbox_reports_no_sandbox(self, tmp_path):
        ex = ActionExecutor(project_root=str(tmp_path))
        # Call the private runner directly with no sandbox created.
        result = ex._run_tests()
        assert result.success is False
        assert "No sandbox" in result.stderr

    def test_run_tests_subprocess_exception_is_caught(self, tmp_path, monkeypatch):
        # If the pytest subprocess raises (e.g. TimeoutExpired), the runner
        # degrades to a failure result rather than propagating the exception.
        import subprocess as _subprocess

        import app.engine.action_executor as mod

        ex = self._project_with_test(tmp_path, "def test_ok():\n    assert True\n")
        ex.create_sandbox()

        def boom(*args, **kwargs):
            raise _subprocess.TimeoutExpired(cmd="pytest", timeout=60)

        monkeypatch.setattr(mod.subprocess, "run", boom)
        result = ex._run_tests()
        assert result.success is False
        assert result.feedback_score == -0.5
        assert "pytest" in result.stderr or "Timeout" in result.stderr
        ex.cleanup()


class TestPromoteAndRollbackDelegates:
    def _patch(self, **kw):
        defaults = dict(file="m.py", finding="eval", action="fix",
                        old_code="eval(x)", new_code="literal_eval(x)", confidence=0.9)
        defaults.update(kw)
        return FractalPatch(**defaults)

    def _exec(self, tmp_path, **kw):
        (tmp_path / "m.py").write_text("y = eval(x)\n")
        return ActionExecutor(project_root=str(tmp_path), **kw)

    def test_promote_without_sandbox_returns_false(self, tmp_path):
        ex = self._exec(tmp_path)
        assert ex.promote_to_original() is False

    def test_promote_marks_journal_record_promoted(self, tmp_path):
        ex = self._exec(tmp_path)
        ex.execute_patch(self._patch())
        assert ex.promote_to_original() is True
        history = ex.get_patch_history()
        assert history and history[0]["promoted"] is True

    def test_rollback_file_restores_specific_file(self, tmp_path):
        ex = self._exec(tmp_path)
        ex.execute_patch(self._patch())
        assert "literal_eval(x)" in (ex.sandbox_dir / "m.py").read_text()
        assert ex.rollback_file("m.py") is True

    def test_rollback_file_unknown_returns_false(self, tmp_path):
        ex = self._exec(tmp_path)
        ex.execute_patch(self._patch())
        assert ex.rollback_file("nope.py") is False

    def test_rollback_all_counts_reverted(self, tmp_path):
        ex = self._exec(tmp_path)
        ex.execute_patch(self._patch())
        assert ex.rollback_all() >= 1

    def test_set_run_id_threads_into_journal(self, tmp_path):
        ex = self._exec(tmp_path)
        ex.set_run_id("run-42")
        ex.execute_patch(self._patch())
        history = ex.get_patch_history()
        assert history and history[0]["run_id"] == "run-42"

    def test_disabled_rollback_makes_delegates_inert(self, tmp_path):
        ex = self._exec(tmp_path, enable_rollback=False)
        ex.execute_patch(self._patch())
        # With no journal, every rollback delegate is a no-op default.
        assert ex.rollback_last() is False
        assert ex.rollback_all() == 0
        assert ex.rollback_file("m.py") is False
        assert ex.get_patch_history() == []

    def test_cleanup_without_sandbox_is_noop(self, tmp_path):
        ex = self._exec(tmp_path)
        # No sandbox was ever created; cleanup must not raise.
        ex.cleanup()
        assert ex.sandbox_dir is None
