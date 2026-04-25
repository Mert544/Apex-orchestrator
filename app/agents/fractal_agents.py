from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
from app.engine.git_auto_commit import GitAutoCommit
from app.policies.mode_policy import ModePolicy, ApexMode
from app.policies.safety_gates import SafetyGates
from app.policy.learning import LearningPolicy


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
        self.planner = Planner(self.feedback, learning_policy=None)
        self.learning_policy = LearningPolicy()
        self.planner.learning_policy = self.learning_policy
        self.git_commit = GitAutoCommit(".")
        self.cache = FractalCache()
        self.cross_run = FractalCrossRunBridge(".")
        self.max_fractal_budget = 10
        self._auto_patch = False
        self._auto_commit = False
        self.parallel = True
        self.max_workers = 4
        self.mode_policy = ModePolicy(mode=ApexMode.REPORT)

    def set_mode_policy(self, policy: ModePolicy) -> None:
        object.__setattr__(self, "mode_policy", policy)
        self.max_fractal_budget = policy.max_fractal_budget
        self._auto_patch = policy.auto_patch
        self._auto_commit = policy.auto_commit

    def set_learning_policy(self, policy: LearningPolicy) -> None:
        self.learning_policy = policy

    @property
    def auto_patch(self) -> bool:
        return self._auto_patch

    @auto_patch.setter
    def auto_patch(self, value: bool) -> None:
        self._auto_patch = value

    @property
    def auto_commit(self) -> bool:
        return self._auto_commit

    @auto_commit.setter
    def auto_commit(self, value: bool) -> None:
        self._auto_commit = value

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        """Override in subclass. Must return dict with 'findings' list."""
        raise NotImplementedError

    def _execute(
        self, project_root: str = ".", max_depth: int = 5, **kwargs: Any
    ) -> dict[str, Any]:
        permissions = self.mode_policy.permissions

        scan_result = self._scan(project_root, **kwargs)
        findings = scan_result.get("findings", [])

        budget = min(len(findings), self.max_fractal_budget)
        targets = findings[:budget]

        decisions = self._decide_batch(targets)

        action_results = []
        commit_results = []
        if self.auto_patch:
            self.executor = ActionExecutor(project_root)
            gates = SafetyGates(
                project_root=project_root,
                max_changed_files=permissions.max_changed_files,
            )

            for decision in decisions:
                if decision.action_type == "patch" and decision.patches:
                    for patch_dict in decision.patches:
                        patch = FractalPatch(**patch_dict)
                        plan = self.planner.plan(decision.finding)
                        strategy = plan.next_strategy()

                        patch_result = self.executor.execute_patch(
                            patch, run_tests=False
                        )

                        test_result = None
                        if patch_result.success:
                            safety_report = gates.check_all(
                                changed_files=[patch.file],
                                old_code=patch.old_code,
                                new_code=patch.new_code,
                                skip_test=False,
                            )
                            if safety_report.blocked:
                                action_results.append(
                                    {
                                        "action_type": "patch",
                                        "success": False,
                                        "patch_applied": False,
                                        "test_success": None,
                                        "changed_files": [],
                                        "feedback_score": -0.5,
                                        "safety_blocked": True,
                                        "safety_summary": safety_report.summary,
                                    }
                                )
                                continue

                            test_result = self.executor._run_tests()

                        overall_success = patch_result.success and (
                            test_result is None or test_result.success
                        )

                        action_results.append(
                            {
                                "action_type": "patch",
                                "success": overall_success,
                                "patch_applied": patch_result.success,
                                "test_success": test_result.success
                                if test_result
                                else None,
                                "changed_files": patch_result.changed_files,
                                "feedback_score": 1.0 if overall_success else -0.5,
                            }
                        )

                        if overall_success:
                            self.executor.promote_to_original()
                            if self.auto_commit and permissions.can_commit:
                                commit = self.git_commit.commit(
                                    changed_files=patch_result.changed_files,
                                    finding=decision.finding.get("issue", "unknown"),
                                    action="fix",
                                )
                                commit_results.append(commit.to_dict())

                        node_key = f"{decision.finding.get('issue', '')}:{decision.finding.get('file', '')}:{decision.finding.get('line', 0)}"
                        old_conf = decision.meta_analysis.get(
                            "aggregate_confidence", 0.5
                        )
                        score = 1.0 if overall_success else -0.5
                        self.feedback.update(node_key, old_conf, score, "patch")

                        if not overall_success:
                            fallback_outcome = self._run_fallback_ladder(
                                decision.finding,
                                patch,
                                gates,
                                plan,
                                decision.patches,
                            )
                            if fallback_outcome:
                                action_results.append(fallback_outcome)

        # Phase 3: Reflection
        reflection = self.reflector.reflect().to_dict()

        # Phase 4: Wire reflection into learning policy
        self.learning_policy.update_from_reflection(reflection)

        # Record findings for cross-run memory
        import uuid

        self.cross_run.record_findings(
            run_id=f"{self.name}-{uuid.uuid4().hex[:8]}", findings=findings
        )

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
            "patches_applied": sum(
                1 for ar in action_results if ar.get("patch_applied")
            ),
            "action_results": action_results,
            "reflection": reflection,
            "commits": commit_results if self.auto_commit else [],
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
                patches = [
                    p.to_dict()
                    for p in self.cortex.fractal_patch_generator.generate(
                        finding, meta.to_dict()
                    )
                ]
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
        else:
            from app.engine.fractal_5whys import FractalNode

            tree = self._rebuild_tree(decision.fractal_tree)
            self.cache.put(finding, tree)

        return decision

    def _decide_batch(
        self, findings: list[dict[str, Any]], max_depth: int = 5
    ) -> list[CortexDecision]:
        """Brain decides for multiple findings."""
        if self.parallel and len(findings) > 1:
            workers = min(self.max_workers, len(findings))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(self._decide_one, f, max_depth) for f in findings
                ]
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

    def _run_fallback_ladder(
        self,
        finding: dict[str, Any],
        original_patch: FractalPatch,
        gates: SafetyGates,
        plan: "Plan",
        all_patches: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Deterministic fallback ladder with 5 tiers.

        Tries in order:
        1. scope_reduce    — reduce patch to minimal change
        2. semantic_patch   — use semantic AST transform
        3. split_patches    — apply one sub-patch at a time
        4. test_first       — validate with tests before applying
        5. review_only     — skip patch, mark for review

        Returns the successful outcome dict or None if all fallbacks failed.
        """
        file_path = original_patch.file
        issue = finding.get("issue", "unknown").lower()

        for strategy in ["scope_reduce", "semantic_patch", "split_patches", "test_first", "review_only"]:
            try:
                if strategy == "scope_reduce":
                    outcome = self._fallback_scope_reduce(finding, original_patch, gates)
                elif strategy == "semantic_patch":
                    outcome = self._fallback_semantic_patch(finding, original_patch, gates)
                elif strategy == "split_patches":
                    outcome = self._fallback_split_patches(finding, all_patches, gates)
                elif strategy == "test_first":
                    outcome = self._fallback_test_first(finding, original_patch, gates)
                elif strategy == "review_only":
                    outcome = self._fallback_review_only(finding, original_patch)
                else:
                    continue

                if outcome and outcome.get("success"):
                    return outcome
            except Exception:
                continue

        return {
            "action_type": "fallback_ladder",
            "strategy": "exhausted",
            "success": False,
            "patch_applied": False,
            "changed_files": [],
            "feedback_score": -0.6,
        }

    def _fallback_scope_reduce(
        self,
        finding: dict[str, Any],
        original_patch: FractalPatch,
        gates: SafetyGates,
    ) -> dict[str, Any]:
        """Tier 1: Reduce patch scope to minimal change."""
        issue = finding.get("issue", "").lower()
        file_path = original_patch.file

        if "eval" in issue:
            new_code = original_patch.new_code.split("# TODO")[0].strip()
        elif "os.system" in issue:
            new_code = original_patch.new_code.split("# TODO")[0].strip()
        elif "bare except" in issue:
            new_code = "except Exception:  # TODO: add specific exception type"
        else:
            new_code = original_patch.new_code

        reduced_patch = FractalPatch(
            file=file_path,
            finding=finding.get("issue", "unknown"),
            action="scope_reduced",
            old_code=original_patch.old_code,
            new_code=new_code,
            confidence=0.7,
            reversible=True,
            patch_source="fallback-scope-reduce",
        )

        result = self.executor.execute_patch(reduced_patch, run_tests=False)
        safety_ok = True
        if result.success:
            safety_report = gates.check_all(
                changed_files=[file_path],
                old_code=reduced_patch.old_code,
                new_code=reduced_patch.new_code,
                skip_test=False,
            )
            safety_ok = not safety_report.blocked

        success = result.success and safety_ok
        if success:
            self.executor.promote_to_original()

        return {
            "action_type": "fallback",
            "strategy": "scope_reduce",
            "success": success,
            "patch_applied": result.success,
            "changed_files": result.changed_files,
            "feedback_score": 0.3 if success else -0.4,
        }

    def _fallback_semantic_patch(
        self,
        finding: dict[str, Any],
        original_patch: FractalPatch,
        gates: SafetyGates,
    ) -> dict[str, Any]:
        """Tier 2: Use semantic AST patch generator."""
        issue = finding.get("issue", "").lower()
        file_path = original_patch.file

        strategy_map = {
            "eval": "fix_eval",
            "os.system": "fix_os_system",
            "bare except": "fix_bare_except",
        }
        sem_strategy = next(
            (v for k, v in strategy_map.items() if k in issue), None
        )
        if not sem_strategy:
            return {"success": False}

        from app.execution.semantic.transforms import security as sec_transforms

        try:
            tree = self._parse_file(file_path)
            if not tree:
                return {"success": False}
            source = self._read_file(file_path)
            if sem_strategy == "fix_eval":
                sem_result = sec_transforms.apply(file_path, source, f"Fix {issue}")
            elif sem_strategy == "fix_os_system":
                sem_result = sec_transforms.apply(file_path, source, f"Fix {issue}")
            elif sem_strategy == "fix_bare_except":
                sem_result = sec_transforms.apply(file_path, source, f"Fix {issue}")
            else:
                return {"success": False}
        except Exception:
            return {"success": False}

        if not sem_result or not sem_result.patch_requests:
            return {"success": False}

        pr = sem_result.patch_requests[0]
        sem_patch = FractalPatch(
            file=file_path,
            finding=finding.get("issue", "unknown"),
            action=sem_strategy,
            old_code=pr.get("expected_old_content", ""),
            new_code=pr.get("new_content", ""),
            confidence=0.85,
            reversible=True,
            patch_source="semantic-fallback",
        )

        result = self.executor.execute_patch(sem_patch, run_tests=False)
        safety_ok = True
        if result.success:
            safety_report = gates.check_all(
                changed_files=[file_path],
                old_code=sem_patch.old_code,
                new_code=sem_patch.new_code,
                skip_test=False,
            )
            safety_ok = not safety_report.blocked

        success = result.success and safety_ok
        if success:
            self.executor.promote_to_original()

        return {
            "action_type": "fallback",
            "strategy": "semantic_patch",
            "success": success,
            "patch_applied": result.success,
            "changed_files": result.changed_files,
            "feedback_score": 0.4 if success else -0.4,
        }

    def _fallback_split_patches(
        self,
        finding: dict[str, Any],
        all_patches: list[dict[str, Any]],
        gates: SafetyGates,
    ) -> dict[str, Any]:
        """Tier 3: Apply patches one at a time instead of batch."""
        file_path = finding.get("file", "")

        if not all_patches:
            return {"success": False}

        sub_patch_dict = all_patches[0]
        sub_patch = FractalPatch(
            file=file_path,
            finding=finding.get("issue", "unknown"),
            action=sub_patch_dict.get("action", "partial"),
            old_code=sub_patch_dict.get("old_code", ""),
            new_code=sub_patch_dict.get("new_code", ""),
            confidence=sub_patch_dict.get("confidence", 0.6),
            reversible=True,
            patch_source="split-fallback",
        )

        result = self.executor.execute_patch(sub_patch, run_tests=False)
        safety_ok = True
        if result.success:
            safety_report = gates.check_all(
                changed_files=[file_path],
                old_code=sub_patch.old_code,
                new_code=sub_patch.new_code,
                skip_test=False,
            )
            safety_ok = not safety_report.blocked

        success = result.success and safety_ok
        if success:
            self.executor.promote_to_original()

        return {
            "action_type": "fallback",
            "strategy": "split_patches",
            "success": success,
            "patch_applied": result.success,
            "changed_files": result.changed_files,
            "feedback_score": 0.3 if success else -0.4,
        }

    def _fallback_test_first(
        self,
        finding: dict[str, Any],
        original_patch: FractalPatch,
        gates: SafetyGates,
    ) -> dict[str, Any]:
        """Tier 4: Run tests first to validate before applying patch."""
        file_path = original_patch.file

        baseline_result = self.executor._run_tests()
        if not baseline_result.success and baseline_result.feedback_score < 0:
            return {
                "action_type": "fallback",
                "strategy": "test_first",
                "success": False,
                "patch_applied": False,
                "changed_files": [],
                "feedback_score": -0.5,
                "reason": "baseline tests already failing",
            }

        new_patch = FractalPatch(
            file=file_path,
            finding=finding.get("issue", "unknown"),
            action="test_first",
            old_code=original_patch.old_code,
            new_code=original_patch.new_code,
            confidence=original_patch.confidence * 0.9,
            reversible=True,
            patch_source="fallback-test-first",
        )

        result = self.executor.execute_patch(new_patch, run_tests=True)
        safety_ok = True
        if result.success:
            safety_report = gates.check_all(
                changed_files=[file_path],
                old_code=new_patch.old_code,
                new_code=new_patch.new_code,
                skip_test=True,
            )
            safety_ok = not safety_report.blocked

        success = result.success and safety_ok
        if success:
            self.executor.promote_to_original()

        return {
            "action_type": "fallback",
            "strategy": "test_first",
            "success": success,
            "patch_applied": result.success,
            "changed_files": result.changed_files,
            "feedback_score": 0.5 if success else -0.5,
        }

    def _fallback_review_only(
        self,
        finding: dict[str, Any],
        original_patch: FractalPatch,
    ) -> dict[str, Any]:
        """Tier 5: Skip patch, flag for human review."""
        return {
            "action_type": "fallback",
            "strategy": "review_only",
            "success": False,
            "patch_applied": False,
            "changed_files": [],
            "feedback_score": 0.0,
            "flagged_for_review": True,
            "review_note": f"Autonomous patch failed; requires human review for {original_patch.file}",
        }

    def _parse_file(self, file_path: str) -> ast.Module | None:
        """Parse a Python file and return AST."""
        try:
            import ast
            path = Path(file_path)
            if path.exists():
                return ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def _read_file(self, file_path: str) -> str:
        """Read file content safely."""
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except Exception:
            return ""

    def _try_fallback_strategy(
        self,
        strategy: str,
        finding: dict[str, Any],
        original_patch: FractalPatch,
        gates: SafetyGates,
    ) -> list[dict[str, Any]]:
        """Legacy fallback strategy handler (delegates to ladder)."""
        outcome = self._run_fallback_ladder(
            finding, original_patch, gates,
            plan=object(), all_patches=[original_patch.to_dict()],
        )
        if outcome:
            return [outcome]
        return []

    def _analyze_parallel(
        self, findings: list[dict[str, Any]], max_depth: int
    ) -> list[dict[str, Any]]:
        """Legacy parallel analysis."""
        workers = min(self.max_workers, len(findings))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._decide_one, f, max_depth) for f in findings]
            results = [f.result() for f in futures]
        return [
            {"tree": r.fractal_tree, "meta": r.meta_analysis, "patches": r.patches}
            for r in results
        ]

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
        super().__init__(
            name=name, role="fractal_security_auditor", bus=bus, context=context
        )

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
        super().__init__(
            name=name, role="fractal_documentation_enforcer", bus=bus, context=context
        )

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        from app.agents.skills import DocstringAgent

        scanner = DocstringAgent()
        result = scanner.run(
            project_root=project_root, patch=kwargs.get("patch", False)
        )
        findings = []
        for gap in result.get("gaps", []):
            findings.append(
                {
                    "issue": "missing_docstring",
                    "file": gap.get("file", ""),
                    "line": gap.get("line", 0),
                    "severity": "low",
                    "target": gap.get("target", ""),
                }
            )
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
        super().__init__(
            name=name, role="fractal_test_coverage_analyst", bus=bus, context=context
        )

    def _scan(self, project_root: str, **kwargs: Any) -> dict[str, Any]:
        from app.agents.skills import TestStubAgent

        scanner = TestStubAgent()
        result = scanner.run(
            project_root=project_root, generate=kwargs.get("generate", False)
        )
        findings = []
        for gap in result.get("gaps", []):
            findings.append(
                {
                    "issue": "missing_test",
                    "file": gap.get("source_file", ""),
                    "line": gap.get("line", 0),
                    "severity": "low",
                    "target": gap.get("function", ""),
                }
            )
        return {
            "gaps_found": result.get("gaps_found", 0),
            "generated_files": result.get("generated_files", []),
            "findings": findings,
        }


class FractalAnalyzerAgent(Agent):
    """Dedicated sub-agent for fractal analysis of a single finding."""

    def __init__(
        self, name: str, finding: dict[str, Any], max_depth: int = 5, **kwargs: Any
    ) -> None:
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
