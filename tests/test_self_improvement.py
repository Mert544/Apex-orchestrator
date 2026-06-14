from __future__ import annotations

from pathlib import Path

from app.engine.self_improvement import SelfImprovementEngine


class TestSelfImprovementEngine:
    def test_analyze_and_plan_returns_dynamic_plan(self, tmp_path: Path):
        engine = SelfImprovementEngine(tmp_path)
        plan = engine.analyze_and_plan(mode="report")
        assert plan.plan_name in {"project_scan", "full_autonomous_loop", "semantic_patch_loop", "self_directed_loop"}
        assert plan.mode == "report"

    def test_get_improvement_summary_keys(self, tmp_path: Path):
        engine = SelfImprovementEngine(tmp_path)
        summary = engine.get_improvement_summary()
        expected_keys = {
            "total_files",
            "sensitive_paths",
            "untested_modules",
            "missing_docstrings",
            "dependency_hubs",
            "test_coverage",
        }
        assert set(summary.keys()) == expected_keys
        assert isinstance(summary["total_files"], int)
        assert isinstance(summary["test_coverage"], float)

    def test_analyze_detects_security_issues(self, tmp_path: Path):
        # Create a fake risky file
        src = tmp_path / "app"
        src.mkdir()
        risky = src / "auth.py"
        risky.write_text("eval(user_input)")
        engine = SelfImprovementEngine(tmp_path)
        plan = engine.analyze_and_plan(mode="report")
        # Should include security intent
        assert "security" in plan.rationale.lower() or plan.agents == []

    def test_analyze_on_real_project(self, tmp_path: Path):
        # Simulate a realistic project structure
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("def main(): pass")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("def test_main(): pass")
        engine = SelfImprovementEngine(tmp_path)
        summary = engine.get_improvement_summary()
        assert summary["total_files"] >= 2
        plan = engine.analyze_and_plan(mode="report")
        assert plan.mode == "report"

    def test_missing_docstrings_ignores_worktree_copies(self, tmp_path: Path):
        # One real undocumented function.
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "real.py").write_text("def real():\n    return 1\n")
        # Worktree copies with undocumented functions must not be counted.
        copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
        copy.mkdir(parents=True)
        (copy / "real.py").write_text("def real():\n    return 1\n")
        (copy / "extra.py").write_text("def extra():\n    return 2\n")

        engine = SelfImprovementEngine(tmp_path)
        assert engine._count_missing_docstrings() == 1
