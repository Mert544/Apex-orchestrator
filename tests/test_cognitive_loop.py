from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.fractal_agents import FractalSecurityAgent
from app.engine.action_executor import ActionExecutor


class TestCognitiveLoop:
    """End-to-end test: Brain decides -> Hands execute -> Feedback updates."""

    def test_brain_decides_no_side_effects(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "unsafe.py").write_text("def f(x):\n    return eval(x)\n")
        agent = FractalSecurityAgent()
        result = agent.run(project_root=str(project), max_depth=3)
        assert result["findings_count"] >= 1
        assert result["patches_applied"] == 0  # Brain does not touch files
        # Original file unchanged
        assert "eval(x)" in (project / "unsafe.py").read_text()

    def test_hands_executes_in_sandbox(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        code = "import ast\ndef f(x):\n    return eval(x)\n"
        (project / "unsafe.py").write_text(code)
        agent = FractalSecurityAgent()
        agent.auto_patch = True
        agent.executor = ActionExecutor(str(project))
        result = agent.run(project_root=str(project), max_depth=3)
        assert result["findings_count"] >= 1
        # Action results should exist
        assert len(result.get("action_results", [])) >= 1
        # Check feedback loop updated confidence
        assert len(agent.feedback.entries) >= 1

    def test_feedback_updates_confidence(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "unsafe.py").write_text("import ast\ndef f(x):\n    return eval(x)\n")
        agent = FractalSecurityAgent()
        agent.auto_patch = True
        agent.executor = ActionExecutor(str(project))
        result = agent.run(project_root=str(project), max_depth=3)
        # Feedback should have positive score (patch applied successfully)
        positive_entries = [e for e in agent.feedback.entries if e.feedback_score > 0]
        assert len(positive_entries) >= 1

    def test_reflection_reports_success(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "unsafe.py").write_text("import ast\ndef f(x):\n    return eval(x)\n")
        agent = FractalSecurityAgent()
        agent.auto_patch = True
        agent.executor = ActionExecutor(str(project))
        result = agent.run(project_root=str(project), max_depth=3)
        reflection = result.get("reflection", {})
        # After successful patch, reflection should note success
        assert reflection.get("total_actions", 0) >= 1
