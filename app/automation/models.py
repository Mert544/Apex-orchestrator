from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AutomationContext:
    project_root: Path
    objective: str
    config: dict[str, Any]
    focus_branch: str | None = None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutomationStep:
    name: str
    skill_name: str


@dataclass
class AutomationStepResult:
    step_name: str
    skill_name: str
    status: str
    output: Any = None
    error: str | None = None


@dataclass
class AutomationRunResult:
    plan_name: str
    steps: list[AutomationStepResult] = field(default_factory=list)
    final_output: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_name": self.plan_name,
            "steps": [
                {
                    "step_name": step.step_name,
                    "skill_name": step.skill_name,
                    "status": step.status,
                    "output": step.output,
                    "error": step.error,
                }
                for step in self.steps
            ],
            "final_output": self.final_output,
        }
