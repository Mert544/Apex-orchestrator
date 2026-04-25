from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.engine.fractal_5whys import Fractal5WhysEngine, FractalNode, MetaAnalysisResult
from app.engine.fractal_patch_generator import FractalPatchGenerator, FractalPatch
from app.execution.semantic_patch_generator import SemanticPatchGenerator


@dataclass
class CortexDecision:
    """A decision produced by the Cortex (brain), executed by Hands."""

    finding: dict[str, Any]
    fractal_tree: dict[str, Any]
    meta_analysis: dict[str, Any]
    action_type: str  # "patch", "review", "ignore", "escalate"
    patches: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""
    patch_source: str = "fractal"  # "fractal" or "semantic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding": self.finding,
            "fractal_tree": self.fractal_tree,
            "meta_analysis": self.meta_analysis,
            "action_type": self.action_type,
            "patches": self.patches,
            "rationale": self.rationale,
            "patch_source": self.patch_source,
        }


class FractalCortex:
    """Pure reasoning layer — no filesystem access, no side effects.

    The Cortex:
    1. Receives a finding
    2. Builds fractal 5-Whys tree
    3. Runs meta-analysis
    4. Decides action type (patch/review/ignore/escalate)
    5. Generates patch plans using semantic transforms when possible

    Usage:
        cortex = FractalCortex()
        decision = cortex.decide(finding)
        # decision.action_type tells Hands what to do
    """

    def __init__(
        self,
        max_depth: int = 5,
        enable_counter_evidence: bool = True,
        use_semantic: bool = True,
    ) -> None:
        self.engine = Fractal5WhysEngine(
            max_depth=max_depth, enable_counter_evidence=enable_counter_evidence
        )
        self.fractal_patch_generator = FractalPatchGenerator()
        self.use_semantic = use_semantic
        if use_semantic:
            self.semantic_patch_generator = SemanticPatchGenerator()

    def decide(
        self, finding: dict[str, Any], project_root: str = "."
    ) -> CortexDecision:
        """Pure reasoning: analyze finding and decide action."""
        tree = self.engine.analyze(finding)

        meta = self.engine.meta_analyze(tree)

        patches = []
        patch_source = "fractal"
        if meta.recommended_action == "patch":
            if self.use_semantic:
                semantic_result = self._generate_semantic_patch(finding, meta)
                if semantic_result and semantic_result.patch_requests:
                    patches = self._convert_semantic_to_fractal_patches(
                        semantic_result, finding
                    )
                    patch_source = "semantic"
            if not patches:
                patches = [
                    p.to_dict()
                    for p in self.fractal_patch_generator.generate(
                        finding, meta.to_dict()
                    )
                ]
                patch_source = "fractal"

        return CortexDecision(
            finding=finding,
            fractal_tree=tree.to_dict(),
            meta_analysis=meta.to_dict(),
            action_type=meta.recommended_action,
            patches=patches,
            rationale=meta.rationale,
            patch_source=patch_source,
        )

    def _generate_semantic_patch(self, finding: dict[str, Any], meta: dict[str, Any]):
        """Try to generate semantic patch for the finding."""
        issue = finding.get("issue", "").lower()
        file_path = finding.get("file", "")
        line = finding.get("line", 0)

        patch_plan = {
            "title": f"Fix {issue}",
            "task_id": f"fractal-{line}",
        }

        if "eval" in issue:
            patch_plan["strategy"] = "fix_eval"
        elif "os.system" in issue:
            patch_plan["strategy"] = "fix_os_system"
        elif "bare except" in issue:
            patch_plan["strategy"] = "fix_bare_except"
        elif "missing_docstring" in issue:
            patch_plan["strategy"] = "add_docstring"
        elif "missing_test" in issue:
            patch_plan["strategy"] = "repair_test"
        else:
            return None

        patch_plan["target_files"] = [file_path]
        patch_plan["targets"] = [{"path": file_path, "type": "file"}]

        try:
            result = self.semantic_patch_generator.generate(
                project_root=".",
                patch_plan=patch_plan,
            )
            return result
        except Exception:
            return None

    def _convert_semantic_to_fractal_patches(
        self, semantic_result, finding: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert SemanticPatchResult to FractalPatch-compatible dicts."""
        patches = []
        file_path = finding.get("file", "")

        for pr in semantic_result.patch_requests:
            patches.append(
                {
                    "file": file_path,
                    "finding": finding.get("issue", "unknown"),
                    "action": semantic_result.transform_type,
                    "old_code": pr.get("expected_old_content", ""),
                    "new_code": pr.get("new_content", ""),
                    "confidence": 0.9
                    if semantic_result.transform_type != "none"
                    else 0.5,
                    "reversible": True,
                    "patch_source": "semantic",
                }
            )
        return patches

    def batch_decide(
        self, findings: list[dict[str, Any]], project_root: str = "."
    ) -> list[CortexDecision]:
        """Reason about multiple findings."""
        return [self.decide(f, project_root) for f in findings]
