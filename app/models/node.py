from __future__ import annotations


from pydantic import BaseModel, Field

from app.models.enums import ClaimType, NodeStatus, StopReason
from app.models.question import Question


class ResearchNode(BaseModel):
    id: str
    claim: str
    parent_ids: list[str] = Field(default_factory=list)
    branch_path: str = ""
    source_question: str | None = None

    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    questions: list[Question] = Field(default_factory=list)

    claim_type: ClaimType = ClaimType.GENERAL
    claim_priority: float = 0.0
    claim_signals: list[str] = Field(default_factory=list)

    confidence: float = 0.0
    quality: float = 0.0
    risk: float = 0.0
    novelty: float = 1.0
    security: float = 1.0
    relevance: float = 1.0
    confidence_reliability: str = ""
    counterfactuals: list[str] = Field(default_factory=list)

    status: NodeStatus = NodeStatus.NEW
    stop_reason: StopReason | None = None
    depth: int = 0
