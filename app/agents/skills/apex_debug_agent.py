"""Apex Debug Agent Skill — Integrates Apex Debug static analysis into the swarm.

This agent runs Apex Debug on target code, parses findings, and feeds them
into the orchestrator's epistemic memory and knowledge graph.

Refactored to use Apex Debug's Python API directly instead of subprocess
for reliability and performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from apex_debug.core.finding import Finding, Severity


@dataclass
class AgentAnalysisResult:
    """Structured result from Apex Debug analysis."""

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
    """Agent skill that runs Apex Debug analysis on code repositories.

    Uses Apex Debug's Python API directly for reliability and speed.

    Usage:
        agent = ApexDebugAgent(project_root="/path/to/code")
        result = agent.run()
        print(f"Found {len(result.findings)} issues")
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
        """Run Apex Debug analysis using the Python API directly.

        Args:
            target: Specific file or directory (default: project_root)
            categories: Filter by categories (security, correctness, performance, style)
            exclude: Directory/file name fragments to skip

        Returns:
            AgentAnalysisResult with findings and metadata
        """
        import time

        from apex_debug.cli.app import _load_config
        from apex_debug.core.session import DebugSession
        from apex_debug.engine.runner import run_pattern_engine, run_pattern_engine_parallel
        from apex_debug.parsers.registry import ParserRegistry

        start = time.perf_counter()
        path = Path(target) if target else self.project_root
        if not path.exists():
            path = self.project_root / path

        if not path.exists():
            return AgentAnalysisResult(
                errors=[f"Target '{target}' not found in {self.project_root}"]
            )

        config = _load_config(path)
        config.min_severity = self.min_severity
        if categories:
            for cat in ("security", "correctness", "performance", "style"):
                setattr(config, f"patterns_{cat}", cat in categories)

        session = DebugSession(config=config)
        parser = ParserRegistry()

        files = parser.discover_files(path, exclude=exclude)
        python_files: list[tuple[Path, str]] = []
        other_files: list[tuple[Path, str, str]] = []

        for filepath in files:
            source = parser.read_file(filepath)
            if source is None:
                continue
            lang = parser.detect_language(filepath)
            if lang == "python":
                python_files.append((filepath, source))
            else:
                other_files.append((filepath, source, lang))

        # Analyze Python files
        if python_files:
            if len(python_files) == 1:
                run_pattern_engine(session, python_files[0][0], python_files[0][1])
            else:
                run_pattern_engine_parallel(session, python_files)

        # Multi-language regex fallback
        if other_files:
            from apex_debug.parsers.multilang import analyze_non_python
            for filepath, source, lang in other_files:
                findings = analyze_non_python(lang, source, str(filepath))
                for f in findings:
                    session.add_finding(f)

        session.finish()
        duration = (time.perf_counter() - start) * 1000

        result = AgentAnalysisResult(
            findings=session.findings,
            files_analyzed=len(files),
            duration_ms=round(duration, 2),
        )
        self._last_result = result
        return result

    def analyze(self, target: Optional[str] = None, **kwargs: Any) -> list[Finding]:
        """Legacy compatibility alias for run(). Returns raw findings list."""
        result = self.run(target=target, **kwargs)
        return result.findings

    def heal(self, dry_run: bool = True) -> dict[str, Any]:
        """Auto-fix safe issues using Apex Debug's autofix.

        Args:
            dry_run: If True, only show what would be fixed

        Returns:
            Summary dict with fixed_files, skipped, errors
        """
        from app.agents.skills.self_healing_agent import SelfHealingAgent

        healer = SelfHealingAgent(self.project_root)
        return healer.heal(dry_run=dry_run)

    def to_epistemic_claims(self, findings: Optional[list[Finding]] = None) -> list[dict]:
        """Convert findings into epistemic memory claims for the orchestrator.

        Returns:
            List of claim dicts compatible with EpistemicMemory
        """
        if findings is None:
            findings = self._last_result.findings if self._last_result else []

        claims: list[dict] = []
        for f in findings:
            claims.append({
                "type": "finding",
                "severity": f.severity.name,
                "category": f.category,
                "title": f.title,
                "message": f.message,
                "location": f.location_str(),
                "confidence": f.confidence,
            })
        return claims

    def summary(self) -> str:
        """Return a human-readable summary of the last analysis."""
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
