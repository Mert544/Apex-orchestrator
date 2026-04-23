from typing import Any

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
    memory_file: str | None = None
    memory_run_id: str | None = None
    known_claim_count: int = 0
    known_question_count: int = 0
    previous_run_count: int = 0
    focus_branch: str | None = None
    focus_claim: str | None = None
    debug_stats: dict[str, int | float] = Field(default_factory=dict)
    estimated_analysis_tokens: int = 0
    estimated_response_tokens: int = 0
    estimated_memory_tokens: int = 0
    estimated_total_tokens: int = 0
    telemetry: dict[str, Any] = Field(default_factory=dict)
    mode: str = "balanced"
    debug_diagnostics: list[str] = Field(default_factory=list)
    debug_report_file: str | None = None
    phase_metrics: dict[str, float] = Field(default_factory=dict)
