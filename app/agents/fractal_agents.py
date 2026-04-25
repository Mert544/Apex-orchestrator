from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agents.base import Agent, AgentMessage
from app.agents.recursive import RecursiveAgent
from app.engine.fractal_5whys import Fractal5WhysEngine
from app.engine.fractal_patch_generator import FractalPatchGenerator, FractalPatch
from app.engine.fractal_cache import FractalCache
from app.engine.fractal_cross_run import FractalCrossRunBridge
from app.engine.fractal_cortex import FractalCortex, CortexDecision
from app.engine.action_executor import ActionExecutor, ActionResult
from app.engine.feedback_loop import FeedbackLoop
from app.engine.reflector import Reflector
from app.engine.planner import Planner


class BaseFractalAgent(RecursiveAgent):
    """Base class for agents that perform fractal deep-analysis on their findings.

    Architecture:
    - Brain (Cortex): Pure reasoning, no side effects
    - Hands (ActionExecutor): Sandboxed execution
    - Feedback (FeedbackLoop): EMA confidence updates
    - Reflection (Reflector): Performance analysis
    - Planning (Planner): Adaptive strategy selection

    Subclasses implement `_scan()` to return raw findings.
    """

    def __init__(self, name: str, role: str, bus=None, context=None) -> None:
        super().__init__(name=name, role=role, bus=bus, context=context)
        self.cortex = FractalCortex(max_depth=5, enable_counter_evidence=True)
        self.executor = ActionExecutor(".")
        self.feedback = FeedbackLoop()
        self.reflector = Reflector(self.feedback)
        self.planner = Planner(self.feedback)
        self.cache = FractalCache()
        self.cross_run = FractalCrossRunBridge(".")
        self.max_fractal_budget = 10
        self.auto_patch = False
        self.parallel = True
        self.max_workers = 4

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        """Override in subclass. Must return dict with 'findings' list."""
        raise NotImplementedError

    def _execute(self, project_root: str = ".", max_depth: int = 5, **kwargs: Any) -> dict[str, Any]:
        scan_result = self._scan(project_root, **kwargs)
        findings = scan_result.get("findings", [])

        budget = min(len(findings), self.max_fractal_budget)
        targets = findings[:budget]

        # Phase 1: Brain (Cortex) decides
        decisions = self._decide_batch(targets)

        # Phase 2: Hands (ActionExecutor) executes if auto_patch enabled
        action_results = []
        if self.auto_patch:
            self.executor = ActionExecutor(project_root)
            for decision in decisions:
                if decision.action_type == "patch" and decision.patches:
                    for patch_dict in decision.patches:
                        patch = FractalPatch(**patch_dict)
                        plan = self.planner.plan(decision.finding)
                        strategy = plan.next_strategy()
                        # Step 1: Apply patch in sandbox
                        patch_result = self.executor.execute_patch(patch, run_tests=False)
                        
                        # Step 2: If patch applied, run tests
                        test_result = None
                        if patch_result.success:
                            test_result = self.executor._run_tests()
                        
                        # Determine overall success
                        overall_success = patch_result.success and (test_result is None or test_result.success)
                        
                        action_results.append({
                            "action_type": "patch",
                            "success": overall_success,
                            "patch_applied": patch_result.success,
                            "test_success": test_result.success if test_result else None,
                            "changed_files": patch_result.changed_files,
                            "feedback_score": 1.0 if overall_success else -0.5,
                        })

                        # Step 3: Promote to original if everything passed
                        if overall_success:
                            self.executor.promote_to_original()

                        # Feedback loop: update confidence
                        node_key = f"{decision.finding.get('issue','')}:{decision.finding.get('file','')}:{decision.finding.get('line',0)}"
                        old_conf = decision.meta_analysis.get("aggregate_confidence", 0.5)
                        score = 1.0 if overall_success else -0.5
                        self.feedback.update(node_key, old_conf, score, "patch")

                        # Retry with fallback if failed
                        if not overall_success:
                            fallback = plan.next_strategy()
                            if fallback:
                                # Try fallback strategy (simplified: just log)
                                pass

        # Phase 3: Reflection
        reflection = self.reflector.reflect().to_dict()

        # Record findings for cross-run memory
        import uuid
        self.cross_run.record_findings(run_id=f"{self.name}-{uuid.uuid4().hex[:8]}", findings=findings)

        fractal_trees = [d.fractal_tree for d in decisions]
        meta_results = [d.meta_analysis for d in decisions]
        generated_patches = []
        for d in decisions:
            generated_patches.extend(d.patches)

        return {
            "agent": self.name,
            "role": self.role,
            **{k: v for k, v in scan_result.items() if k != "findings"},
            "findings_count": len(findings),
            "fractal_analyzed": len(decisions),
            "findings": findings,
            "fractal_trees": fractal_trees,
            "meta_analyses": meta_results,
            "generated_patches": generated_patches,
            "patches_applied": sum(1 for p in generated_patches if p.get("applied")),
            "action_results": action_results,
            "reflection": reflection,
        }

    def _normalize_finding(self, finding: dict[str, Any]) -> dict[str, Any]:
        """Normalize finding keys for fractal engine compatibility."""
        normalized = dict(finding)
        if "risk_type" in normalized and "issue" not in normalized:
            normalized["issue"] = normalized["risk_type"]
        return normalized

    def _decide_one(self, finding: dict[str, Any], max_depth: int) -> CortexDecision:
        """Brain decides action for a single finding (pure reasoning, no side effects)."""
        finding = self._normalize_finding(finding)
        cached = self.cache.get(finding)
        if cached:
            # Reconstruct decision from cached tree
            meta = self.cortex.engine.meta_analyze(cached)
            patches = []
            if meta.recommended_action == "patch":
                patches = [p.to_dict() for p in self.cortex.patch_generator.generate(finding, meta.to_dict())]
            return CortexDecision(
                finding=finding,
                fractal_tree=cached.to_dict(),
                meta_analysis=meta.to_dict(),
                action_type=meta.recommended_action,
                patches=patches,
                rationale=meta.rationale,
            )

        # Fresh analysis via Cortex
        decision = self.cortex.decide(finding)
        # Broadcast fractal analysis complete
        if self.bus:
            self.bus.broadcast(
                sender=self.name,
                topic="fractal.analysis.complete",
                payload={
                    "finding": finding,
                    "tree_depth": decision.fractal_tree.get("level", 1),
                    "root_question": decision.fractal_tree.get("question", ""),
                },
            )
        # Cache the tree
        from app.engine.fractal_5whys import FractalNode
        tree = self._rebuild_tree(decision.fractal_tree)
        self.cache.put(finding, tree)
        return decision

    def _decide_batch(self, findings: list[dict[str, Any]], max_depth: int = 5) -> list[CortexDecision]:
        """Brain decides for multiple findings."""
        if self.parallel and len(findings) > 1:
            workers = min(self.max_workers, len(findings))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(self._decide_one, f, max_depth) for f in findings]
                return [f.result() for f in futures]
        return [self._decide_one(f, max_depth) for f in findings]

    def _rebuild_tree(self, data: dict[str, Any]) -> FractalNode:
        """Rebuild FractalNode from dict (for caching)."""
        from app.engine.fractal_5whys import FractalNode
        node = FractalNode(
            level=data["level"],
            question=data["question"],
            answer=data["answer"],
            confidence=data["confidence"],
            evidence=data.get("evidence", []),
            counter_evidence=data.get("counter_evidence", []),
            rebuttal=data.get("rebuttal", ""),
            metadata=data.get("metadata", {}),
        )
        for child in data.get("children", []):
            node.children.append(self._rebuild_tree(child))
        return node

    def _analyze_parallel(self, findings: list[dict[str, Any]], max_depth: int) -> list[dict[str, Any]]:
        """Legacy parallel analysis."""
        workers = min(self.max_workers, len(findings))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._decide_one, f, max_depth) for f in findings]
            results = [f.result() for f in futures]
        return [{"tree": r.fractal_tree, "meta": r.meta_analysis, "patches": r.patches} for r in results]

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
