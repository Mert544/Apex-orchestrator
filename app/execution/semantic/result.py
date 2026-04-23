from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SemanticPatchResult:
    patch_requests: list[dict[str, Any]] = field(default_factory=list)
    transform_type: str = "none"
    rationale: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    mode: str = "semantic"
    selected_targets: list[dict[str, Any]] = field(default_factory=list)
    extracted_contexts: list[dict[str, Any]] = field(default_factory=list)
    chosen_strategy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
