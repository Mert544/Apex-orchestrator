from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.learning import AgentLearning


class TestAgentLearning:
    def test_record_and_get_tips(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        learning.record_result("security", "eval", success=True)
        learning.record_result("security", "eval", success=True)
        learning.record_result("security", "eval", success=False)
        tips = learning.get_tips("security")
        assert "eval" in tips
        assert tips["eval"]["success_rate"] == pytest.approx(0.67, 0.01)
        assert tips["eval"]["total_runs"] == 3

    def test_ema_confidence(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        for _ in range(5):
            learning.record_result("security", "eval", success=True)
        tips = learning.get_tips("security")
        assert tips["eval"]["ema_confidence"] > 0.8

    def test_priority_list(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        learning.record_result("a", "pattern_high", success=True)
        learning.record_result("a", "pattern_high", success=True)
        learning.record_result("a", "pattern_low", success=False)
        priorities = learning.get_priority_list("a")
        assert priorities[0] == "pattern_high"

    def test_should_skip_failing_pattern(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        for _ in range(5):
            learning.record_result("a", "bad", success=False)
        assert learning.should_skip("a", "bad", min_ema=0.3) is True

    def test_should_not_skip_new_pattern(self, tmp_path: Path):
        learning = AgentLearning(tmp_path)
        assert learning.should_skip("a", "new_pattern") is False

    def test_persistence(self, tmp_path: Path):
        l1 = AgentLearning(tmp_path)
        l1.record_result("x", "y", success=True)
        l2 = AgentLearning(tmp_path)
        tips = l2.get_tips("x")
        assert "y" in tips
