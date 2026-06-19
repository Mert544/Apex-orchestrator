from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.automation.planner import DynamicPlan

from app.automation.planner import AutonomousPlanner
from app.engine.skip_dirs import iter_source_files
from app.intent.parser import IntentParser
from app.tools.project_profile import ProjectProfiler


class SelfImprovementEngine:
    """Run Apex Orchestrator on its own codebase to find and fix gaps.

    Usage:
        engine = SelfImprovementEngine(project_root=Path("."))
        plan = engine.analyze_and_plan()
        # plan is a DynamicPlan ready for AdaptiveRunner
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self.intent_parser = IntentParser()
        self.planner = AutonomousPlanner()
        self.profiler = ProjectProfiler(root=self.project_root)

    def analyze_and_plan(self, mode: str = "supervised") -> "DynamicPlan":
        """Profile the project and build a self-improvement plan."""
        profile = self.profiler.profile()

        # Build a synthetic intent based on profile findings
        intent_parts: list[str] = ["self-improve"]
        if profile.sensitive_paths:
            intent_parts.append("security")
        if profile.untested_modules:
            intent_parts.append("test coverage")
        if profile.dependency_hubs:
            intent_parts.append("dependency")

        goal = " ".join(intent_parts)
        intent = self.intent_parser.parse(goal, explicit_mode=mode)
        # Convert dataclass to dict for planner compatibility
        profile_dict = {
            "total_files": profile.total_files,
            "sensitive_paths": profile.sensitive_paths,
            "dependency_hubs": profile.dependency_hubs,
            "untested_modules": profile.untested_modules,
            "critical_untested_modules": profile.critical_untested_modules,
            "test_coverage": 0.0,  # Not directly tracked by ProjectProfiler
        }
        return self.planner.build_plan(intent, project_profile=profile_dict)

    def get_improvement_summary(self) -> dict:
        """Return a quick summary of improvement opportunities."""
        profile = self.profiler.profile()
        return {
            "total_files": profile.total_files,
            "sensitive_paths": len(profile.sensitive_paths),
            "untested_modules": len(profile.untested_modules),
            "missing_docstrings": self._count_missing_docstrings(),
            "dependency_hubs": len(profile.dependency_hubs),
            "test_coverage": 0.0,
        }

    def _count_missing_docstrings(self) -> int:
        """Count functions/classes lacking a docstring via an AST scan."""
        missing = 0
        for path in iter_source_files(self.project_root):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, UnicodeDecodeError, RecursionError, MemoryError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))) and (not ast.get_docstring(node)):
                    missing += 1
        return missing
