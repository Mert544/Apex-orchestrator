from __future__ import annotations

from typing import Any

from app.models.node import ResearchNode
from app.skills.claim_analyzer import ClaimAnalyzer


class NodeFactory:
    """Factory for creating ResearchNode instances."""

    def __init__(self, claim_analyzer: ClaimAnalyzer | None = None) -> None:
        self.claim_analyzer = claim_analyzer or ClaimAnalyzer()

    def make_node(
        self,
        id: str,
        claim: str,
        depth: int,
        parent_ids: list[str] | None = None,
        branch_path: str = "",
        source_question: str | None = None,
    ) -> ResearchNode:
        analysis = self.claim_analyzer.analyze(claim)
        return ResearchNode(
            id=id,
            claim=claim,
            parent_ids=parent_ids or [],
            depth=depth,
            branch_path=branch_path,
            source_question=source_question,
            claim_type=analysis.claim_type,
            claim_priority=analysis.priority,
            claim_signals=analysis.signals,
        )


class FocusBranchResolver:
    """Resolve focus branch claims from memory state."""

    @staticmethod
    def resolve(focus_branch: str, memory_state: Any) -> tuple[str | None, str | None]:
        state = memory_state if isinstance(memory_state, dict) else {}
        full_report = state.get("last_full_report", {}) if isinstance(state.get("last_full_report", {}), dict) else {}
        last_report = state.get("last_report", {}) if isinstance(state.get("last_report", {}), dict) else {}

        for candidate in (full_report, last_report):
            branch_map = candidate.get("branch_map", {}) if isinstance(candidate, dict) else {}
            branch_questions = candidate.get("branch_questions", {}) if isinstance(candidate, dict) else {}
            claim = branch_map.get(focus_branch)
            if claim:
                return claim, branch_questions.get(focus_branch)
        return None, None
