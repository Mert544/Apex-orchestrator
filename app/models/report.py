from pydantic import BaseModel, Field


class FinalReport(BaseModel):
    objective: str
    main_findings: list[str] = Field(default_factory=list)
    confidence_map: dict[str, float] = Field(default_factory=dict)
    claim_types: dict[str, str] = Field(default_factory=dict)
    claim_priorities: dict[str, float] = Field(default_factory=dict)
    branch_map: dict[str, str] = Field(default_factory=dict)
    branch_questions: dict[str, str] = Field(default_factory=dict)
    strongest_supporting_evidence: list[str] = Field(default_factory=list)
    strongest_opposing_evidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    stopped_branches: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
