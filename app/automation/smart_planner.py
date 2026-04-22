from __future__ import annotations

from typing import Any


class SmartPlanner:
    """Select the best automation plan based on project health signals.

    Usage:
        planner = SmartPlanner()
        plan = planner.select_plan(project_profile, has_uncommitted_changes=False)
    """

    def select_plan(self, profile: dict[str, Any], has_uncommitted_changes: bool = False) -> str:
        return self.select_plan_with_rationale(profile, has_uncommitted_changes)["plan"]

    def select_plan_with_rationale(
        self, profile: dict[str, Any], has_uncommitted_changes: bool = False
    ) -> dict[str, str]:
        untested = len(profile.get("critical_untested_modules", []))
        hubs = len(profile.get("dependency_hubs", []))
        sensitive = len(profile.get("sensitive_paths", []))
        coverage = profile.get("test_coverage", 0.0)
        total_files = profile.get("total_files", 0)

        # Priority 1: Uncommitted changes → commit first
        if has_uncommitted_changes:
            return {"plan": "git_pr_loop", "rationale": "Uncommitted changes detected. Staging and summarizing first."}

        # Priority 2: Many issues across the board → full autonomous
        issue_score = untested + hubs + sensitive
        if issue_score >= 5 or coverage < 0.3:
            return {
                "plan": "full_autonomous_loop",
                "rationale": f"High issue density ({issue_score} areas) and low coverage ({coverage:.0%}). Running full autonomous remediation.",
            }

        # Priority 3: Untested modules → semantic patches
        if untested >= 1:
            return {
                "plan": "semantic_patch_loop",
                "rationale": f"Found {untested} untested module(s). Generating docstrings, stubs, and basic guards.",
            }

        # Priority 4: Many dependency hubs → deep scan
        if hubs >= 3 or total_files >= 40:
            return {
                "plan": "project_scan",
                "rationale": f"Project has {hubs} dependency hubs and {total_files} files. Full fractal scan recommended.",
            }

        # Priority 5: Sensitive paths → safety check
        if sensitive >= 1:
            return {
                "plan": "verify_project",
                "rationale": f"Found {sensitive} sensitive path(s). Running verification and safety checks.",
            }

        # Default: quick verify
        return {
            "plan": "verify_project",
            "rationale": "Project looks healthy. Running quick verification.",
        }
