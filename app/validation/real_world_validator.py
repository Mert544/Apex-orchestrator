from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer
from app.tools.project_profile import ProjectProfiler


class RealWorldValidator:
    """Validate that Apex detects known issues in real-world-style projects.

    This suite runs lightweight analysis on example projects and checks
    that expected issues are surfaced.
    """

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root)

    def run(self) -> dict[str, Any]:
        profile = ProjectProfiler(self.root).profile()
        fn_analyzer = FunctionFractalAnalyzer()
        fn_results = []
        for py_file in self.root.rglob("*.py"):
            if "test_" in py_file.name:
                continue
            fn_results.extend(fn_analyzer.analyze_file(py_file))

        # Build risk registry
        all_risks = []
        for r in fn_results:
            all_risks.extend(r["risks"])

        return {
            "project": str(self.root),
            "total_files": profile.total_files,
            "functions_analyzed": len(fn_results),
            "risks_found": all_risks,
            "risk_count": len(all_risks),
            "critical_untested": profile.critical_untested_modules,
        }

    def assert_expected_issues(self, expected: list[str]) -> dict[str, Any]:
        result = self.run()
        risks_lower = [r.lower() for r in result["risks_found"]]
        found = []
        missing = []
        for exp in expected:
            if any(exp.lower() in rl for rl in risks_lower):
                found.append(exp)
            else:
                missing.append(exp)
        return {
            "all_found": len(missing) == 0,
            "found": found,
            "missing": missing,
            "total_risks": result["risk_count"],
        }
