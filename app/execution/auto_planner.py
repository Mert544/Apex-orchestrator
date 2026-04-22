from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AutoPlanResult:
    tasks: list[dict[str, Any]] = field(default_factory=list)
    patch_plan: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "patch_plan": self.patch_plan,
            "rationale": self.rationale,
        }


class AutoPlanner:
    """Generate tasks and patch plans automatically from research report.

    This is a rule-based planner that inspects the report for:
    - untested modules → test stub tasks
    - missing docstrings → docstring tasks
    - dependency hubs → type annotation tasks
    - sensitive paths → guard clause tasks
    """

    def plan(self, report: dict[str, Any]) -> AutoPlanResult:
        actions = report.get("recommended_actions", [])
        branch_map = report.get("branch_map", {})
        profile = report.get("project_profile", {})

        tasks = []
        patch_plan = {"target_files": [], "title": "", "change_strategy": []}
        rationales = []

        # 1. Untested modules → add docstrings + test stubs
        untested = profile.get("critical_untested_modules", [])
        if untested:
            for mod in untested[:3]:  # max 3 to keep scope safe
                tasks.append({
                    "title": f"Add docstring and test stub for {mod}",
                    "id": f"auto-{mod}",
                    "target_files": [mod.replace(".", "/") + ".py"],
                })
            patch_plan["target_files"].extend([m.replace(".", "/") + ".py" for m in untested[:3]])
            patch_plan["change_strategy"].append("add docstrings")
            patch_plan["change_strategy"].append("create test stubs")
            rationales.append(f"Found {len(untested)} untested modules; adding docstrings and stubs.")

        # 2. Dependency hubs → type annotations
        hubs = profile.get("dependency_hubs", [])
        if hubs:
            for hub in hubs[:2]:
                hub_file = hub if "/" in hub else hub.replace(".", "/") + ".py"
                tasks.append({
                    "title": f"Add type annotations to {hub}",
                    "id": f"auto-type-{hub}",
                    "target_files": [hub_file],
                })
                patch_plan["target_files"].append(hub_file)
            patch_plan["change_strategy"].append("add type annotations")
            rationales.append(f"Found {len(hubs)} dependency hubs; adding type annotations for clarity.")

        # 3. Sensitive paths → guard clauses
        sensitive = profile.get("sensitive_paths", [])
        if sensitive:
            for sp in sensitive[:2]:
                sp_file = sp if "/" in sp else sp.replace(".", "/") + ".py"
                tasks.append({
                    "title": f"Add input validation to {sp}",
                    "id": f"auto-guard-{sp}",
                    "target_files": [sp_file],
                })
                patch_plan["target_files"].append(sp_file)
            patch_plan["change_strategy"].append("add guard clauses")
            rationales.append(f"Found {len(sensitive)} sensitive paths; adding input guards.")

        patch_plan["title"] = tasks[0]["title"] if tasks else "Auto-generated improvements"

        return AutoPlanResult(
            tasks=tasks,
            patch_plan=patch_plan,
            rationale=" ".join(rationales) if rationales else "No high-priority actions detected.",
        )
