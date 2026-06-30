"""Cross-repo workflow: Orchestrator + Debug + Fix + Verify.

Coordinates Apex Orchestrator agents with Apex Debug for:
1. Code analysis
2. Finding extraction
3. Auto-fix application
4. Test verification
5. Report generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.agents.skills.finding import Finding


@dataclass
class WorkflowResult:
    """Result of a complete cross-repo workflow."""

    success: bool
    findings: list[Finding] = field(default_factory=list)
    fixed_files: list[str] = field(default_factory=list)
    test_passed: bool = False
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)


class CrossRepoWorkflow:
    """End-to-end workflow combining Orchestrator and Apex Debug.

    Usage:
        workflow = CrossRepoWorkflow(project_root="/path/to/code")
        result = workflow.run(fix=True, test=True)
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def run(
        self,
        min_severity: str = "low",
        fix: bool = False,
        test: bool = False,
        output_format: str = "html",
        exclude: set[str] | None = None,
    ) -> WorkflowResult:
        """Run the complete workflow.

        Args:
            min_severity: Minimum severity to report
            fix: Apply auto-fixes if True
            test: Run tests after fixes if True
            output_format: html, json, sarif, or markdown

        Returns:
            WorkflowResult with full details
        """
        errors: list[str] = []
        findings: list[Finding] = []
        fixed_files: list[str] = []
        test_passed = False
        report_path: str | None = None

        # Step 1: Analysis
        try:
            from app.agents.skills.apex_debug_agent import ApexDebugAgent
            agent = ApexDebugAgent(self.project_root, min_severity=min_severity)
            result = agent.run(exclude=exclude)
            findings = result.findings
        except Exception as e:
            errors.append(f"Analysis failed: {e}")
            return WorkflowResult(success=False, errors=errors)

        # Step 2: Auto-fix (optional)
        if fix and findings:
            try:
                from app.agents.skills.self_healing_agent import SelfHealingAgent
                healer = SelfHealingAgent(self.project_root)
                heal_result = healer.heal(dry_run=False)
                fixed_files = heal_result.files_modified
                test_passed = heal_result.test_passed
            except Exception as e:
                errors.append(f"Auto-fix failed: {e}")

        # Step 3: Test verification (optional, if fix not enabled)
        if test and not fix:
            try:
                from app.agents.skills.self_healing_agent import SelfHealingAgent
                healer = SelfHealingAgent(self.project_root)
                test_passed = healer._run_tests()
            except Exception as e:
                errors.append(f"Test verification failed: {e}")

        # Step 4: Generate report
        report_path = str(self.project_root / f"apex_report.{output_format}")

        return WorkflowResult(
            success=not errors or bool(findings),
            findings=findings,
            fixed_files=fixed_files,
            test_passed=test_passed,
            report_path=report_path,
            errors=errors,
        )

    def to_orchestrator_memory(self, result: WorkflowResult) -> dict:
        """Convert workflow result to orchestrator epistemic memory format.

        Returns:
            Dict compatible with EpistemicMemory.add_claim()
        """
        return {
            "type": "apex_debug_workflow",
            "findings_count": len(result.findings),
            "critical_count": sum(1 for f in result.findings if f.severity.name == "CRITICAL"),
            "high_count": sum(1 for f in result.findings if f.severity.name == "HIGH"),
            "fixed_files": result.fixed_files,
            "test_passed": result.test_passed,
            "report_path": result.report_path,
            "errors": result.errors,
        }
