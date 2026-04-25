from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Plan:
    """A plan with fallback strategies."""

    primary: str
    fallbacks: list[str] = field(default_factory=list)
    max_retries: int = 2
    current_attempt: int = 0

    def next_strategy(self) -> str | None:
        """Get next strategy when primary fails."""
        if self.current_attempt == 0:
            self.current_attempt += 1
            return self.primary
        idx = self.current_attempt - 1
        if idx < len(self.fallbacks):
            self.current_attempt += 1
            return self.fallbacks[idx]
        return None

    def reset(self) -> None:
        self.current_attempt = 0


class Planner:
    """Adaptive planner: chooses strategy based on finding type, past performance, and learned policy.

    The Planner:
    1. Receives a finding
    2. Looks up past success/failure in FeedbackLoop
    3. Checks LearningPolicy for skip/escalate/boost signals
    4. Chooses primary strategy + fallbacks
    5. If action fails, retries with fallback

    Usage:
        planner = Planner()
        plan = planner.plan(finding)
        strategy = plan.next_strategy()  # primary
        # if fails:
        strategy = plan.next_strategy()  # fallback 1
    """

    def __init__(self, feedback=None, learning_policy=None) -> None:
        from app.engine.feedback_loop import FeedbackLoop

        self.feedback = feedback or FeedbackLoop()
        self.learning_policy = learning_policy

    def plan(self, finding: dict[str, Any]) -> Plan:
        """Create a plan for handling a finding."""
        issue = finding.get("issue", "").lower()
        node_key = f"{finding.get('issue', '')}:{finding.get('file', '')}:{finding.get('line', 0)}"

        if self.learning_policy and self.learning_policy.should_skip_finding(finding):
            return Plan(
                primary="skip",
                fallbacks=["escalate"],
                max_retries=1,
            )

        if self.feedback.should_skip(node_key):
            return Plan(
                primary="escalate",
                fallbacks=[],
                max_retries=0,
            )

        issue_type = self._extract_issue_type(issue)
        if self._is_known_false_positive_pattern(issue_type):
            return Plan(
                primary="review",
                fallbacks=["escalate"],
                max_retries=1,
            )

        confidence_boost = self._get_confidence_boost(issue_type)

        if self.learning_policy:
            adj = self.learning_policy.get_adjustments(issue_type)
            if adj["escalate"]:
                return Plan(
                    primary="escalate",
                    fallbacks=["skip"],
                    max_retries=1,
                )
            if adj["preferred_strategy"]:
                pref = adj["preferred_strategy"]
                return Plan(
                    primary=pref,
                    fallbacks=["escalate"],
                    max_retries=1,
                )

        if "eval" in issue:
            return Plan(
                primary="replace_with_literal_eval",
                fallbacks=["add_input_validation", "escalate"],
                max_retries=2,
            )
        elif "os.system" in issue:
            return Plan(
                primary="replace_with_subprocess_run",
                fallbacks=["add_command_whitelist", "escalate"],
                max_retries=2,
            )
        elif "bare except" in issue:
            return Plan(
                primary="add_exception_type",
                fallbacks=["escalate"],
                max_retries=1,
            )
        elif "missing_docstring" in issue:
            return Plan(
                primary="add_docstring",
                fallbacks=["escalate"],
                max_retries=1,
            )
        else:
            return Plan(
                primary="review",
                fallbacks=["escalate"],
                max_retries=1,
            )

    def _extract_issue_type(self, issue: str) -> str:
        """Extract the type portion from issue string."""
        if ":" in issue:
            return issue.split(":")[0].strip()
        return issue.strip()

    def _is_known_false_positive_pattern(self, issue_type: str) -> bool:
        """Check if this issue type is a known false positive from past reflection."""
        type_key = f"type:{issue_type}"
        avg = self.feedback.get_average_feedback(type_key)
        return avg < -0.3

    def _get_confidence_boost(self, issue_type: str) -> float:
        """Get confidence boost based on past success with this issue type."""
        type_key = f"type:{issue_type}"
        avg = self.feedback.get_average_feedback(type_key)
        if avg > 0.3:
            return 0.1
        elif avg < -0.3:
            return -0.1
        return 0.0

    def record_action_result(self, finding: dict[str, Any], success: bool) -> None:
        """Record action result for future learning."""
        issue = finding.get("issue", "").lower()
        issue_type = self._extract_issue_type(issue)
        node_key = f"{finding.get('issue', '')}:{finding.get('file', '')}:{finding.get('line', 0)}"

        score = 1.0 if success else -0.5
        self.feedback.update(node_key, 0.5, score, "patch")

        type_key = f"type:{issue_type}"
        self.feedback.update(type_key, 0.5, score, "type_pattern")
