from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedIntent:
    """Result of parsing a user's natural-language goal."""

    goal: str
    plan_type: str  # e.g. "project_scan", "semantic_patch_loop", "full_autonomous_loop"
    agents: list[str] = field(default_factory=list)
    mode: str = "supervised"  # "report" | "supervised" | "autonomous"
    rationale: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


class IntentParser:
    """Parse natural-language goals into structured automation plans.

    Deterministic keyword-based matching (no LLM required).
    """

    # Keywords → (plan_type, [agents])
    _INTENT_MAP: dict[str, tuple[str, list[str]]] = {
        # Security
        "security": ("full_autonomous_loop", ["security_agent"]),
        "güvenlik": ("full_autonomous_loop", ["security_agent"]),
        "risk": ("full_autonomous_loop", ["security_agent"]),
        "vulnerability": ("full_autonomous_loop", ["security_agent"]),
        # Testing
        "test": ("semantic_patch_loop", ["test_stub_agent"]),
        "coverage": ("semantic_patch_loop", ["test_stub_agent"]),
        "stub": ("semantic_patch_loop", ["test_stub_agent"]),
        # Documentation
        "docstring": ("semantic_patch_loop", ["docstring_agent"]),
        "documentation": ("semantic_patch_loop", ["docstring_agent"]),
        "docs": ("semantic_patch_loop", ["docstring_agent"]),
        # Dependencies
        "dependency": ("project_scan", ["dependency_agent"]),
        "import": ("project_scan", ["dependency_agent"]),
        "coupling": ("project_scan", ["dependency_agent"]),
        # General scan
        "scan": ("project_scan", []),
        "analyze": ("project_scan", []),
        "review": ("project_scan", []),
        "inspect": ("project_scan", []),
        # Fixing / patching
        "fix": ("semantic_patch_loop", []),
        "repair": ("semantic_patch_loop", []),
        "patch": ("semantic_patch_loop", []),
        "improve": ("semantic_patch_loop", []),
        "refactor": ("semantic_patch_loop", []),
        # Full autonomous
        "autonomous": ("full_autonomous_loop", []),
        "full": ("full_autonomous_loop", []),
        "end-to-end": ("full_autonomous_loop", []),
        # Self-improvement
        "self-improve": ("self_directed_loop", []),
        "self improve": ("self_directed_loop", []),
        "apex on apex": ("self_directed_loop", []),
    }

    _MODE_KEYWORDS: dict[str, list[str]] = {
        "report": ["report", "audit only", "dry-run", "dry run", "sadece rapor"],
        "autonomous": ["autonomous", "auto", "otomatik", "no-confirm", "no confirm"],
    }

    def parse(self, goal: str, explicit_mode: str | None = None) -> ParsedIntent:
        goal_lower = goal.lower()
        tokens = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]+", goal_lower)

        # Determine mode
        mode = explicit_mode or self._detect_mode(goal_lower)

        # Match intent keywords
        matched_plans: dict[str, int] = {}
        matched_agents: set[str] = set()

        for keyword, (plan_type, agents) in self._INTENT_MAP.items():
            if keyword in goal_lower or any(t == keyword for t in tokens):
                matched_plans[plan_type] = matched_plans.get(plan_type, 0) + 1
                matched_agents.update(agents)

        if not matched_plans:
            # Default fallback
            return ParsedIntent(
                goal=goal,
                plan_type="project_scan",
                agents=[],
                mode=mode,
                rationale="No specific intent detected. Running general project scan.",
            )

        # Pick plan with highest score; tie-break toward more comprehensive
        plan_scores = {
            "project_scan": 1,
            "semantic_patch_loop": 2,
            "full_autonomous_loop": 3,
            "self_directed_loop": 4,
        }
        best_plan = max(
            matched_plans.keys(),
            key=lambda p: (matched_plans[p], plan_scores.get(p, 0)),
        )

        rationale = self._build_rationale(goal, best_plan, list(matched_agents), mode)

        return ParsedIntent(
            goal=goal,
            plan_type=best_plan,
            agents=sorted(matched_agents),
            mode=mode,
            rationale=rationale,
        )

    def _detect_mode(self, goal_lower: str) -> str:
        for mode, keywords in self._MODE_KEYWORDS.items():
            if any(kw in goal_lower for kw in keywords):
                return mode
        return "supervised"

    def _build_rationale(self, goal: str, plan: str, agents: list[str], mode: str) -> str:
        agent_str = f" using {', '.join(agents)}" if agents else ""
        mode_str = f" in {mode} mode"
        return f"Detected intent '{goal}'{agent_str}. Selected plan '{plan}'{mode_str}."
