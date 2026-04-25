from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LearningPolicy:
    """Learning policy that translates reflection into strategy adjustments.

    The LearningPolicy:
    1. Receives ReflectionReport from Reflector
    2. Extracts actionable adjustments (skip, boost, lower confidence, escalate)
    3. Provides lookup methods for Planner to consult during strategy selection

    Usage:
        policy = LearningPolicy()
        policy.update_from_reflection(reflection_report)
        adjustments = policy.get_adjustments("eval")
        if adjustments.skip:
            return Plan(primary="skip", ...)
    """

    skip_issue_types: set[str] = field(default_factory=set)
    confidence_boosts: dict[str, float] = field(default_factory=dict)
    escalated_types: set[str] = field(default_factory=set)
    lowered_types: set[str] = field(default_factory=set)
    recommended_strategies: dict[str, str] = field(default_factory=dict)
    total_feedback_entries: int = 0
    last_updated: str = ""

    def update_from_reflection(self, reflection: dict[str, Any]) -> None:
        """Update policy from a ReflectionReport dict."""
        self.total_feedback_entries = reflection.get("total_actions", 0)
        self.skip_issue_types.clear()
        self.confidence_boosts.clear()
        self.escalated_types.clear()
        self.lowered_types.clear()
        self.recommended_strategies.clear()

        for fp in reflection.get("top_false_positives", []):
            node_key = fp.get("node_key", "")
            avg_score = fp.get("average_feedback", 0)
            occurrences = fp.get("occurrences", 0)

            if avg_score < -0.5 and occurrences >= 3:
                self.skip_issue_types.add(node_key)
            elif avg_score < -0.3:
                self.lowered_types.add(node_key)

        for rec in reflection.get("recommendations", []):
            rec_lower = rec.lower()
            if "high false positive" in rec_lower:
                self.escalated_types.add("false_positive_pattern")

        self.last_updated = reflection.get("timestamp", "")

    def get_adjustments(self, issue_type: str) -> dict[str, Any]:
        """Get strategy adjustments for a given issue type.

        Returns:
            dict with keys: skip, boost, lower, escalate, preferred_strategy
        """
        skip = issue_type in self.skip_issue_types

        boost = self.confidence_boosts.get(issue_type, 0.0)
        lower = issue_type in self.lowered_types
        escalate = issue_type in self.escalated_types
        preferred = self.recommended_strategies.get(issue_type, "")

        return {
            "skip": skip,
            "boost": boost,
            "lower": lower,
            "escalate": escalate,
            "preferred_strategy": preferred,
        }

    def should_skip_finding(self, finding: dict[str, Any]) -> bool:
        """Check if finding should be skipped based on learning history."""
        issue = finding.get("issue", "")
        node_key = f"{issue}:{finding.get('file', '')}:{finding.get('line', 0)}"
        return node_key in self.skip_issue_types

    def get_preferred_strategy(self, issue: str) -> str | None:
        """Get preferred strategy for given issue type, or None for default."""
        return self.recommended_strategies.get(issue, None)

    def merge_from_feedback(self, feedback_entries: list[Any]) -> None:
        """Merge learning from raw feedback entries."""
        from collections import defaultdict

        by_type: defaultdict[str, list[float]] = defaultdict(list)
        for entry in feedback_entries:
            parts = entry.node_key.split(":")
            if len(parts) >= 1:
                issue_type = parts[0]
                by_type[issue_type].append(entry.feedback_score)

        for issue_type, scores in by_type.items():
            if len(scores) >= 3:
                avg = sum(scores) / len(scores)
                if avg > 0.4:
                    self.confidence_boosts[issue_type] = 0.1
                elif avg < -0.4:
                    self.skip_issue_types.add(issue_type)
                    self.lowered_types.add(issue_type)