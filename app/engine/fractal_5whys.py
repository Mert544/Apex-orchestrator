from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FractalNode:
    """A single node in the fractal analysis tree.

    Each node represents one 'Why?' answer, spawning deeper nodes.
    Optionally includes counter-evidence (self-scrutiny layer).
    """

    level: int
    question: str
    answer: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    counter_evidence: list[str] = field(default_factory=list)
    rebuttal: str = ""
    children: list["FractalNode"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "question": self.question,
            "answer": self.answer,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "counter_evidence": self.counter_evidence,
            "rebuttal": self.rebuttal,
            "children": [c.to_dict() for c in self.children],
            "metadata": self.metadata,
        }


@dataclass
class MetaAnalysisResult:
    """Meta-analysis of a complete fractal tree."""

    aggregate_confidence: float
    depth_reached: int
    node_count: int
    recommended_action: str  # "patch", "review", "ignore", "escalate"
    rationale: str
    key_insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_confidence": self.aggregate_confidence,
            "depth_reached": self.depth_reached,
            "node_count": self.node_count,
            "recommended_action": self.recommended_action,
            "rationale": self.rationale,
            "key_insights": self.key_insights,
        }


class CounterEvidenceGenerator:
    """Generate counter-arguments for each fractal node (self-scrutiny layer).

    This makes Apex intellectually honest: every claim is challenged.
    """

    def generate(self, node: FractalNode, finding: dict[str, Any]) -> tuple[list[str], str]:
        issue = finding.get("issue", "").lower()
        answer = node.answer.lower()

        counter = []
        rebuttal = ""

        if "eval" in issue and "convenience" in answer:
            counter = [
                "Developer may have used eval() for a legitimate dynamic expression need",
                "ast.literal_eval() does not support all use cases (e.g., arithmetic)",
                "The input may already be sanitized elsewhere in the call chain",
            ]
            rebuttal = "Even with sanitization, eval() remains a critical attack surface. Replace with safer alternatives."

        elif "os.system" in issue and "convenience" in answer:
            counter = [
                "subprocess.run() requires more boilerplate for simple commands",
                "The command may be hardcoded, not user-controlled",
            ]
            rebuttal = "Hardcoded commands can still be exploited via PATH manipulation. Use subprocess with explicit args."

        elif "missing_docstring" in issue:
            counter = [
                "The function name may be self-explanatory",
                "Internal helper functions often lack docstrings by convention",
            ]
            rebuttal = "Self-documenting names are insufficient for complex logic. Docstrings aid IDE autocomplete and onboarding."

        elif "missing_test" in issue:
            counter = [
                "The function may be covered indirectly by integration tests",
                "Trivial getters/setters do not always need dedicated tests",
            ]
            rebuttal = "Indirect coverage is brittle. Explicit unit tests document expected behavior and catch regressions."

        else:
            counter = ["This analysis is based on pattern matching, not runtime behavior.",
                       "The finding may be a false positive."]
            rebuttal = "Pattern-based detection has known limitations. Validate with manual review or dynamic analysis."

        return counter, rebuttal


class Fractal5WhysEngine:
    """Recursively ask 'Why?' up to N levels deep for every finding.

    This is the core of Apex's fractal intelligence:
    - Level 1: What is the risk? (surface)
    - Level 2: Why does it exist? (cause)
    - Level 3: Why was it introduced? (origin)
    - Level 4: Why wasn't it caught? (process gap)
    - Level 5: Why does the system allow it? (architecture gap)
    - Layer 6+: Counter-evidence & rebuttal (self-scrutiny)

    Usage:
        engine = Fractal5WhysEngine(max_depth=5)
        tree = engine.analyze(finding={"issue": "eval() usage", "file": "auth.py"})
        meta = engine.meta_analyze(tree)
    """

    def __init__(self, max_depth: int = 5, min_confidence: float = 0.3, enable_counter_evidence: bool = True) -> None:
        self.max_depth = max_depth
        self.min_confidence = min_confidence
        self.enable_counter_evidence = enable_counter_evidence
        self.counter_gen = CounterEvidenceGenerator()

    def analyze(self, finding: dict[str, Any]) -> FractalNode:
        """Build a fractal analysis tree for a single finding."""
        issue = finding.get("issue", "Unknown issue")
        file = finding.get("file", "unknown")
        severity = finding.get("severity", "info")

        root = FractalNode(
            level=1,
            question=f"What is the risk: {issue}?",
            answer=f"{severity.upper()} severity issue in {file}",
            confidence=1.0,
            evidence=[f"Detected in {file}"],
            metadata={"finding": finding},
        )

        self._deepen(root, finding)

        if self.enable_counter_evidence:
            self._inject_counter_evidence(root, finding)

        return root

    def _deepen(self, parent: FractalNode, finding: dict[str, Any]) -> None:
        """Recursively spawn deeper 'Why?' nodes."""
        if parent.level >= self.max_depth:
            return

        next_level = parent.level + 1
        generators = [
            self._why_exists,
            self._why_introduced,
            self._why_missed,
            self._why_allowed,
        ]

        if next_level - 2 < len(generators):
            generator = generators[next_level - 2]
            child = generator(next_level, finding, parent)
            if child.confidence >= self.min_confidence:
                parent.children.append(child)
                self._deepen(child, finding)

    def _inject_counter_evidence(self, node: FractalNode, finding: dict[str, Any]) -> None:
        """Walk tree and add counter-evidence to every node."""
        counter, rebuttal = self.counter_gen.generate(node, finding)
        node.counter_evidence = counter
        node.rebuttal = rebuttal
        for child in node.children:
            self._inject_counter_evidence(child, finding)

    def _why_exists(self, level: int, finding: dict[str, Any], parent: FractalNode) -> FractalNode:
        """Level 2: Why does this risk exist?"""
        issue = finding.get("issue", "")
        if "eval" in issue.lower():
            return FractalNode(
                level=level,
                question="Why does eval() exist in this code?",
                answer="Developer used dynamic execution instead of safer alternatives",
                confidence=0.9,
                evidence=["eval() allows arbitrary code execution"],
            )
        elif "os.system" in issue.lower():
            return FractalNode(
                level=level,
                question="Why does os.system() exist in this code?",
                answer="Developer used shell execution for convenience",
                confidence=0.85,
                evidence=["os.system() is easier than subprocess.run()"],
            )
        elif "missing_docstring" in issue.lower():
            return FractalNode(
                level=level,
                question="Why are docstrings missing?",
                answer="No documentation requirement in the team's coding standards",
                confidence=0.8,
                evidence=["No linter rule enforces docstrings"],
            )
        else:
            return FractalNode(
                level=level,
                question=f"Why does {issue} exist?",
                answer="Root cause not yet determined",
                confidence=0.5,
                evidence=["Requires manual investigation"],
            )

    def _why_introduced(self, level: int, finding: dict[str, Any], parent: FractalNode) -> FractalNode:
        """Level 3: Why was this introduced?"""
        issue = finding.get("issue", "")
        if "eval" in issue.lower():
            return FractalNode(
                level=level,
                question="Why was eval() introduced instead of safer parsing?",
                answer="Developer may not have known about ast.literal_eval or json.loads",
                confidence=0.75,
                evidence=["Knowledge gap in secure coding practices"],
            )
        elif "missing_docstring" in issue.lower():
            return FractalNode(
                level=level,
                question="Why were docstring requirements not enforced?",
                answer="Code review process does not check documentation",
                confidence=0.8,
                evidence=["No docstring checks in CI pipeline"],
            )
        else:
            return FractalNode(
                level=level,
                question="Why was this pattern introduced?",
                answer="Lack of secure coding guidelines during development",
                confidence=0.6,
                evidence=["Team may not have security training"],
            )

    def _why_missed(self, level: int, finding: dict[str, Any], parent: FractalNode) -> FractalNode:
        """Level 4: Why wasn't this caught earlier?"""
        return FractalNode(
            level=level,
            question="Why wasn't this caught in code review or testing?",
            answer="Security scanning is not part of the CI pipeline",
            confidence=0.85,
            evidence=["No automated security checks in pre-commit or CI"],
        )

    def _why_allowed(self, level: int, finding: dict[str, Any], parent: FractalNode) -> FractalNode:
        """Level 5: Why does the architecture allow this?"""
        return FractalNode(
            level=level,
            question="Why does the system architecture permit this risk?",
            answer="No input validation layer or sandboxing at the application boundary",
            confidence=0.8,
            evidence=["Architecture lacks defense-in-depth strategy"],
        )

    def analyze_batch(self, findings: list[dict[str, Any]]) -> list[FractalNode]:
        """Analyze multiple findings, returning a forest of fractal trees."""
        return [self.analyze(f) for f in findings]

    def summarize_tree(self, node: FractalNode) -> str:
        """Generate a human-readable summary of the fractal analysis."""
        lines = [f"Level {node.level}: {node.question}", f"  → {node.answer}"]
        if node.counter_evidence:
            lines.append("  ⚠️ Counter-evidence:")
            for ce in node.counter_evidence:
                lines.append(f"    • {ce}")
            lines.append(f"  🛡️ Rebuttal: {node.rebuttal}")
        for child in node.children:
            lines.append(self.summarize_tree(child))
        return "\n".join(lines)

    def meta_analyze(self, tree: FractalNode) -> MetaAnalysisResult:
        """Evaluate the entire fractal tree and recommend an action."""
        confidences = []
        node_count = 0
        max_level = 0

        def walk(node: FractalNode) -> None:
            nonlocal node_count, max_level
            node_count += 1
            max_level = max(max_level, node.level)
            confidences.append(node.confidence)
            for c in node.children:
                walk(c)

        walk(tree)

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        # Penalize shallow trees and trees with low-confidence nodes
        depth_penalty = 1.0 if max_level >= self.max_depth else 0.8
        aggregate = avg_conf * depth_penalty

        # Determine action
        issue = tree.metadata.get("finding", {}).get("issue", "").lower()
        severity = tree.metadata.get("finding", {}).get("severity", "info")

        if severity == "critical" and aggregate > 0.7:
            action = "patch"
            rationale = "High-confidence critical finding with deep root-cause analysis. Auto-patch recommended."
        elif severity in ("critical", "high") and aggregate > 0.5:
            action = "review"
            rationale = "Significant finding with moderate confidence. Human review required before patch."
        elif aggregate < 0.3:
            action = "ignore"
            rationale = "Low aggregate confidence. Likely false positive or insufficient evidence."
        else:
            action = "escalate"
            rationale = "Complex finding with mixed signals. Escalate to senior engineer."

        insights = [
            f"Tree depth: {max_level}/{self.max_depth}",
            f"Nodes analyzed: {node_count}",
            f"Average node confidence: {avg_conf:.0%}",
            f"Aggregate confidence: {aggregate:.0%}",
        ]

        return MetaAnalysisResult(
            aggregate_confidence=aggregate,
            depth_reached=max_level,
            node_count=node_count,
            recommended_action=action,
            rationale=rationale,
            key_insights=insights,
        )
