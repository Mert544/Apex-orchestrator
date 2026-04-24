from __future__ import annotations

from typing import Any

from app.agents.base import Agent, AgentMessage
from app.agents.recursive import RecursiveAgent
from app.engine.fractal_5whys import Fractal5WhysEngine


class BaseFractalAgent(RecursiveAgent):
    """Base class for agents that perform fractal deep-analysis on their findings.

    Subclasses implement `_scan()` to return raw findings.
    Base class automatically runs fractal 5-Whys on each finding.
    """

    def __init__(self, name: str, role: str, bus=None, context=None) -> None:
        super().__init__(name=name, role=role, bus=bus, context=context)
        self.fractal_engine = Fractal5WhysEngine(max_depth=5)
        self.max_fractal_budget = 10

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        """Override in subclass. Must return dict with 'findings' list."""
        raise NotImplementedError

    def _execute(self, project_root: str = ".", max_depth: int = 5, **kwargs: Any) -> dict[str, Any]:
        scan_result = self._scan(project_root, **kwargs)
        findings = scan_result.get("findings", [])

        fractal_trees = []
        budget = min(len(findings), self.max_fractal_budget)
        for finding in findings[:budget]:
            sub = self.spawn_fractal_analyzer(finding, max_depth)
            if sub:
                fractal_trees.append(sub.to_dict())

        return {
            "agent": self.name,
            "role": self.role,
            **{k: v for k, v in scan_result.items() if k != "findings"},
            "findings_count": len(findings),
            "fractal_analyzed": len(fractal_trees),
            "findings": findings,
            "fractal_trees": fractal_trees,
        }

    def spawn_fractal_analyzer(self, finding: dict[str, Any], max_depth: int) -> Any:
        engine = Fractal5WhysEngine(max_depth=max_depth)
        tree = engine.analyze(finding)
        if self.bus:
            self.bus.broadcast(
                sender=self.name,
                topic="fractal.analysis.complete",
                payload={
                    "finding": finding,
                    "tree_depth": max_depth,
                    "root_question": tree.question,
                },
            )
        return tree


class FractalSecurityAgent(BaseFractalAgent):
    """Security agent with fractal deep-analysis capability."""

    def __init__(self, name: str = "fractal-security", bus=None, context=None) -> None:
        super().__init__(name=name, role="fractal_security_auditor", bus=bus, context=context)

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        from app.agents.skills import SecurityAgent
        scanner = SecurityAgent()
        return scanner.run(project_root=project_root)


class FractalDocstringAgent(BaseFractalAgent):
    """Docstring agent with fractal deep-analysis.

    Finds missing docstrings, then performs 5-Whys analysis on why
    documentation gaps exist.
    """

    def __init__(self, name: str = "fractal-docstring", bus=None, context=None) -> None:
        super().__init__(name=name, role="fractal_documentation_enforcer", bus=bus, context=context)

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        from app.agents.skills import DocstringAgent
        scanner = DocstringAgent()
        result = scanner.run(project_root=project_root, patch=kwargs.get("patch", False))
        findings = []
        for gap in result.get("gaps", []):
            findings.append({
                "issue": "missing_docstring",
                "file": gap.get("file", ""),
                "line": gap.get("line", 0),
                "severity": "low",
                "target": gap.get("target", ""),
            })
        return {
            "gaps_found": result.get("gaps_found", 0),
            "patched_files": result.get("patched_files", []),
            "findings": findings,
        }


class FractalTestStubAgent(BaseFractalAgent):
    """Test-stub agent with fractal deep-analysis.

    Finds untested functions, then performs 5-Whys analysis on why
    test coverage is missing.
    """

    def __init__(self, name: str = "fractal-test-stub", bus=None, context=None) -> None:
        super().__init__(name=name, role="fractal_test_coverage_analyst", bus=bus, context=context)

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        from app.agents.skills import TestStubAgent
        scanner = TestStubAgent()
        result = scanner.run(project_root=project_root, generate=kwargs.get("generate", False))
        findings = []
        for gap in result.get("gaps", []):
            findings.append({
                "issue": "missing_test",
                "file": gap.get("source_file", ""),
                "line": gap.get("line", 0),
                "severity": "low",
                "target": gap.get("function", ""),
            })
        return {
            "gaps_found": result.get("gaps_found", 0),
            "generated_files": result.get("generated_files", []),
            "findings": findings,
        }


class FractalAnalyzerAgent(Agent):
    """Dedicated sub-agent for fractal analysis of a single finding."""

    def __init__(self, name: str, finding: dict[str, Any], max_depth: int = 5, **kwargs: Any) -> None:
        super().__init__(name=name, role="fractal_analyzer", **kwargs)
        self.finding = finding
        self.max_depth = max_depth
        self.engine = Fractal5WhysEngine(max_depth=max_depth)

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        tree = self.engine.analyze(self.finding)
        return {
            "agent": self.name,
            "finding": self.finding,
            "fractal_tree": tree.to_dict(),
            "depth": self.max_depth,
        }
