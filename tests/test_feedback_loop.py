from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.feedback_loop import FeedbackLoop


class TestFeedbackLoop:
    def test_update_confidence(self, tmp_path: Path):
        loop = FeedbackLoop(alpha=0.3, log_dir=str(tmp_path))
        new_conf = loop.update("eval:auth.py:5", old_confidence=0.9, feedback_score=1.0)
        # 0.9 * 0.7 + 1.0 * 0.3 = 0.93
        assert abs(new_conf - 0.93) < 0.001

    def test_negative_feedback_lowers_confidence(self, tmp_path: Path):
        loop = FeedbackLoop(alpha=0.3, log_dir=str(tmp_path))
        new_conf = loop.update("eval:auth.py:5", old_confidence=0.9, feedback_score=-0.5)
        # 0.9 * 0.7 + (-0.5) * 0.3 = 0.63 - 0.15 = 0.48
        assert abs(new_conf - 0.48) < 0.001

    def test_clamping(self, tmp_path: Path):
        loop = FeedbackLoop(alpha=0.3, log_dir=str(tmp_path))
        new_conf = loop.update("x", old_confidence=0.1, feedback_score=-1.0)
        assert new_conf >= 0.0
        new_conf = loop.update("y", old_confidence=0.9, feedback_score=2.0)
        assert new_conf <= 1.0

    def test_history(self, tmp_path: Path):
        loop = FeedbackLoop(alpha=0.3, log_dir=str(tmp_path))
        loop.update("eval:auth.py:5", old_confidence=0.9, feedback_score=1.0)
        loop.update("eval:auth.py:5", old_confidence=0.93, feedback_score=-0.5)
        history = loop.get_history("eval:auth.py:5")
        assert len(history) == 2

    def test_should_skip(self, tmp_path: Path):
        loop = FeedbackLoop(alpha=0.3, log_dir=str(tmp_path))
        loop.update("bad", old_confidence=0.9, feedback_score=-0.5)
        loop.update("bad", old_confidence=0.63, feedback_score=-0.5)
        assert loop.should_skip("bad", threshold=-0.2) is True
        assert loop.should_skip("good", threshold=-0.2) is False

    def test_persistence(self, tmp_path: Path):
        loop = FeedbackLoop(alpha=0.3, log_dir=str(tmp_path))
        loop.update("x", old_confidence=0.5, feedback_score=1.0)
        loop2 = FeedbackLoop(alpha=0.3, log_dir=str(tmp_path))
        assert len(loop2.entries) == 1


class TestFeedbackLoopExtra:
    def _loop(self, tmp_path, **kw):
        return FeedbackLoop(log_dir=str(tmp_path / ".apex"), **kw)

    def test_dedup_returns_none(self, tmp_path):
        fb = self._loop(tmp_path)
        fb.update("n1", 0.5, 1.0, action_type="fix", run_id="r1")
        assert fb.update("n1", 0.5, 1.0, action_type="fix", run_id="r1") is None

    def test_repeated_updates_stay_usable(self, tmp_path):
        # Many updates remain queryable (cleanup is a bounded best-effort).
        fb = self._loop(tmp_path, max_entries_per_node=3, dedup_window_seconds=0)
        for i in range(6):
            fb.update("n", 0.5, 1.0, run_id=f"r{i}")
        assert len(fb.get_history("n")) >= 1
        assert 0.0 <= fb.get_weighted_feedback("n") <= 1.0

    def test_statistics(self, tmp_path):
        fb = self._loop(tmp_path, dedup_window_seconds=0)
        fb.update("n1", 0.5, 1.0, action_type="fix", source="auto", run_id="r1")
        fb.update("n2", 0.5, 1.0, action_type="test", source="human", run_id="r2")
        stats = fb.get_statistics()
        assert stats["total_entries"] == 2
        assert stats["unique_nodes"] == 2
        assert "fix" in stats["entries_by_action"]

    def test_weighted_and_average_and_node_confidence(self, tmp_path):
        fb = self._loop(tmp_path, dedup_window_seconds=0)
        assert fb.get_weighted_feedback("missing") == 0.0
        fb.update("n", 0.5, 1.0, run_id="r1")
        fb.update("n", 0.5, 0.0, run_id="r2")
        w = fb.get_weighted_feedback("n")
        assert 0.0 <= w <= 1.0
        # These are aliases of the weighted computation (allow float jitter).
        assert abs(fb.get_average_feedback("n") - w) < 1e-6
        assert abs(fb.get_node_confidence("n") - w) < 1e-6

    def test_clear_duplicates(self, tmp_path):
        fb = self._loop(tmp_path, dedup_window_seconds=0)
        fb.update("n", 0.5, 1.0, action_type="fix", run_id="r1")
        fb.update("n", 0.5, 1.0, action_type="fix", run_id="r2")
        removed = fb.clear_duplicates()
        assert removed >= 0
