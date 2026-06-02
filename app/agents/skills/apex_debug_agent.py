"""Apex Debug Agent Skill — static analysis using Apex's own engines.

Runs Apex's built-in SecurityAgent (AST-based) over a repository, normalizes
the results into self-contained Finding objects, and feeds them into the
orchestrator's epistemic memory. No external dependency — fully in-process.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.agents.skills.finding import Finding, Severity

# Map SecurityAgent severities to our ordered Severity + a category.
_SEVERITY = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
}


@dataclass
class AgentAnalysisResult:
    """Structured result from an analysis run."""

    findings: list[Finding] = field(default_factory=list)
    files_analyzed: int = 0
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.MEDIUM)

    @property
    def security_count(self) -> int:
        return sum(1 for f in self.findings if f.category == "security")

    def by_category(self, category: str) -> list[Finding]:
        return [f for f in self.findings if f.category == category]

    def by_severity(self, min_sev: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity >= min_sev]


class ApexDebugAgent:
    """Run Apex's own static analysis on a repository.

    Usage:
        agent = ApexDebugAgent(project_root="/path/to/code")
        result = agent.run()
        for f in result.findings:
            print(f"  [{f.severity.name}] {f.title} at {f.location_str()}")
    """

    def __init__(self, project_root: str | Path, min_severity: str = "low") -> None:
        self.project_root = Path(project_root).resolve()
        self.min_severity = min_severity
        self._last_result: Optional[AgentAnalysisResult] = None

    def run(
        self,
        target: Optional[str] = None,
        categories: Optional[list[str]] = None,
        exclude: Optional[set[str]] = None,
    ) -> AgentAnalysisResult:
        """Run security analysis via Apex's SecurityAgent (AST-based, in-process)."""
        from app.agents.skills.security_agent import SecurityAgent

        start = time.perf_counter()
        path = Path(target) if target else self.project_root
        if not path.exists():
            path = self.project_root / path
        if not path.exists():
            return AgentAnalysisResult(errors=[f"Target '{target}' not found in {self.project_root}"])

        try:
            scan = SecurityAgent().run(project_root=str(path))
        except Exception as exc:  # never let analysis crash the workflow
            return AgentAnalysisResult(errors=[f"Analysis failed: {exc}"])

        min_sev = Severity.from_name(self.min_severity)
        findings: list[Finding] = []
        for raw in scan.get("findings", []):
            sev = _SEVERITY.get(str(raw.get("severity", "low")).lower(), Severity.LOW)
            if sev < min_sev:
                continue
            title = raw.get("risk_type") or raw.get("risk") or raw.get("details") or "issue"
            findings.append(Finding(
                title=str(title),
                message=str(raw.get("details") or raw.get("suggestion") or ""),
                category="security",
                severity=sev,
                file=str(raw.get("file", "")),
                line=int(raw.get("line", 0) or 0),
            ))

        if categories and "security" not in categories:
            findings = []  # only the security category is produced in-process

        result = AgentAnalysisResult(
            findings=findings,
            files_analyzed=int(scan.get("scanned_files", 0) or 0),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        self._last_result = result
        return result

    def analyze(self, target: Optional[str] = None, **kwargs: Any) -> list[Finding]:
        """Alias for run() that returns the raw findings list."""
        return self.run(target=target, **kwargs).findings

    def heal(self, dry_run: bool = True) -> dict[str, Any]:
        """Auto-fix safe issues using Apex's own self-healing agent."""
        from app.agents.skills.self_healing_agent import SelfHealingAgent

        result = SelfHealingAgent(self.project_root).heal(dry_run=dry_run)
        return {
            "success": result.success,
            "files_modified": result.files_modified,
            "test_passed": result.test_passed,
            "message": result.message,
        }

    def to_epistemic_claims(self, findings: Optional[list[Finding]] = None) -> list[dict]:
        """Convert findings into epistemic memory claims for the orchestrator."""
        if findings is None:
            findings = self._last_result.findings if self._last_result else []
        return [
            {
                "type": "finding",
                "severity": f.severity.name,
                "category": f.category,
                "title": f.title,
                "message": f.message,
                "location": f.location_str(),
                "confidence": f.confidence,
            }
            for f in findings
        ]

    def summary(self) -> str:
        """Human-readable summary of the last analysis."""
        if not self._last_result:
            return "No analysis run yet."
        r = self._last_result
        lines = [
            "Apex Debug Analysis Summary",
            f"  Files analyzed: {r.files_analyzed}",
            f"  Duration: {r.duration_ms}ms",
            f"  Findings: {len(r.findings)} total",
            f"    CRITICAL: {r.critical_count}",
            f"    HIGH: {r.high_count}",
            f"    MEDIUM: {r.medium_count}",
            f"  Security issues: {r.security_count}",
        ]
        if r.errors:
            lines.append(f"  Errors: {len(r.errors)}")
        return "\n".join(lines)
