from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.skills import SecurityAgent
from app.agents.learning import AgentLearning


class TestSecurityAgentAutoTuning:
    def test_skips_failing_pattern(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        for _ in range(5):
            learning.record_result("security", "eval", success=False)

        agent = SecurityAgent(learning=learning)
        assert "eval" not in agent.patterns

    def test_keeps_good_pattern(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        for _ in range(5):
            learning.record_result("security", "eval", success=True)

        agent = SecurityAgent(learning=learning)
        assert "eval" in agent.patterns

    def test_record_result(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        agent = SecurityAgent(learning=learning)
        agent.record_result("eval", success=True)
        tips = learning.get_tips("security")
        assert "eval" in tips

    def test_no_learning_by_default(self):
        agent = SecurityAgent()
        assert agent.learning is None
        assert "eval" in agent.patterns
