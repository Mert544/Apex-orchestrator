from __future__ import annotations

import pytest

from app.policy.learning import LearningPolicy


class TestLearningPolicy:
    def test_init(self):
        policy = LearningPolicy()
        assert policy.skip_issue_types == set()
        assert policy.confidence_boosts == {}
        assert policy.escalated_types == set()
        assert policy.lowered_types == set()

    def test_update_from_reflection_high_false_positive(self):
        policy = LearningPolicy()
        reflection = {
            "total_actions": 50,
            "success_rate": 0.4,
            "false_positive_rate": 0.6,
            "top_false_positives": [
                {
                    "node_key": "eval:src/file.py:10",
                    "average_feedback": -0.6,
                    "occurrences": 5,
                    "recommendation": "Consider skipping or escalating.",
                }
            ],
            "recommendations": [
                "High false positive rate (60%). Consider tightening detection patterns."
            ],
        }
        policy.update_from_reflection(reflection)
        assert "eval:src/file.py:10" in policy.skip_issue_types
        assert "false_positive_pattern" in policy.escalated_types

    def test_update_from_reflection_no_data(self):
        policy = LearningPolicy()
        reflection = {
            "total_actions": 0,
            "success_rate": 0.0,
            "false_positive_rate": 0.0,
            "top_false_positives": [],
            "recommendations": ["No feedback history yet."],
        }
        policy.update_from_reflection(reflection)
        assert len(policy.skip_issue_types) == 0

    def test_get_adjustments(self):
        policy = LearningPolicy()
        policy.skip_issue_types.add("eval:src/x.py:1")
        policy.confidence_boosts["docstring"] = 0.1
        policy.lowered_types.add("os.system")
        policy.escalated_types.add("shell_injection")
        policy.recommended_strategies["missing_docstring"] = "add_docstring"

        adj = policy.get_adjustments("docstring")
        assert adj["skip"] is False
        assert adj["boost"] == 0.1
        assert adj["lower"] is False
        assert adj["escalate"] is False
        assert adj["preferred_strategy"] == ""

        adj_skip = policy.get_adjustments("eval:src/x.py:1")
        assert adj_skip["skip"] is True

    def test_should_skip_finding(self):
        policy = LearningPolicy()
        policy.skip_issue_types.add("eval:src/file.py:10")

        assert policy.should_skip_finding({
            "issue": "eval",
            "file": "src/file.py",
            "line": 10,
        }) is True

        assert policy.should_skip_finding({
            "issue": "eval",
            "file": "src/file.py",
            "line": 20,
        }) is False

    def test_get_preferred_strategy(self):
        policy = LearningPolicy()
        policy.recommended_strategies["missing_docstring"] = "add_docstring"
        policy.recommended_strategies["bare except"] = "add_exception_type"

        assert policy.get_preferred_strategy("missing_docstring") == "add_docstring"
        assert policy.get_preferred_strategy("unknown") is None

    def test_merge_from_feedback(self):
        from app.engine.feedback_loop import FeedbackEntry
        from datetime import datetime

        policy = LearningPolicy()
        entries = [
            FeedbackEntry(
                node_key="eval:src/a.py:1",
                old_confidence=0.5,
                new_confidence=0.65,
                feedback_score=0.8,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
            FeedbackEntry(
                node_key="eval:src/a.py:1",
                old_confidence=0.65,
                new_confidence=0.72,
                feedback_score=0.7,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
            FeedbackEntry(
                node_key="eval:src/a.py:1",
                old_confidence=0.72,
                new_confidence=0.78,
                feedback_score=0.6,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
            FeedbackEntry(
                node_key="os.system:src/b.py:5",
                old_confidence=0.5,
                new_confidence=0.35,
                feedback_score=-0.5,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
            FeedbackEntry(
                node_key="os.system:src/b.py:5",
                old_confidence=0.35,
                new_confidence=0.23,
                feedback_score=-0.6,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
            FeedbackEntry(
                node_key="os.system:src/b.py:5",
                old_confidence=0.23,
                new_confidence=0.15,
                feedback_score=-0.5,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
        ]

        policy.merge_from_feedback(entries)
        assert "eval" in policy.confidence_boosts
        assert "os.system" in policy.skip_issue_types
        assert "os.system" in policy.lowered_types

    def test_merge_from_feedback_insufficient_data(self):
        from app.engine.feedback_loop import FeedbackEntry
        from datetime import datetime

        policy = LearningPolicy()
        entries = [
            FeedbackEntry(
                node_key="eval:src/a.py:1",
                old_confidence=0.5,
                new_confidence=0.65,
                feedback_score=0.8,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
            FeedbackEntry(
                node_key="eval:src/a.py:1",
                old_confidence=0.65,
                new_confidence=0.72,
                feedback_score=0.7,
                action_type="patch",
                timestamp=datetime.now().isoformat(),
            ),
        ]
        policy.merge_from_feedback(entries)
        assert "eval" not in policy.confidence_boosts
        assert "eval" not in policy.skip_issue_types