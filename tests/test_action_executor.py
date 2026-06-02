from __future__ import annotations

from pathlib import Path

from app.engine.action_executor import ActionExecutor
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
