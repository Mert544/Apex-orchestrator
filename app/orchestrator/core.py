from __future__ import annotations

import time
from typing import Any, Callable

from app.engine.budget import BudgetController
from app.engine.compressed_mode import CompressedModeEngine
from app.engine.debug_engine import DebugEngine
from app.engine.novelty import NoveltyScorer
from app.engine.termination import TerminationEngine
from app.execution.token_telemetry import TokenTelemetry
from app.llm.router import LLMRouter
from app.memory.graph_store import GraphStore
from app.models.enums import NodeStatus, StopReason
from app.models.node import ResearchNode
from app.agents.evaluator import ClaimEvaluator
from app.orchestrator.factory import FocusBranchResolver, NodeFactory
from app.orchestrator.metrics import PhaseMetrics
from app.orchestrator.report_composer import ReportComposer
from app.policies.constitution import (
    downgrade_if_unsupported,
    enforce_four_question_types,
    must_search_counter_evidence,
)
from app.policies.scoring import score_confidence, score_question_priority
from app.skills.assumption_extractor import AssumptionExtractor
from app.skills.claim_analyzer import ClaimAnalyzer
from app.skills.claim_normalizer import ClaimNormalizer
from app.skills.question_generator import QuestionGenerator
from app.skills.quality_judge import QualityJudge
from app.skills.security_governor import SecurityGovernor
from app.skills.spam_guard import SpamGuard
from app.utils.branching import make_branch_path


class FractalResearchOrchestrator:
    def __init__(self, config: dict[str, Any], decomposer, validator, synthesizer, memory_store=None, debug: DebugEngine | None = None) -> None:
        self._compressed = CompressedModeEngine(config)
        self.config = self._compressed.config

        self.decomposer = decomposer
        self.validator = validator
        self.synthesizer = synthesizer
        self.memory_store = memory_store

        self.debug = debug or DebugEngine(enabled=bool(config.get("debug_enabled", False)))

        budget_limit = int(self.config.get("token_budget_limit", 0))
        self.telemetry = TokenTelemetry(budget_limit=budget_limit)
        self.llm = LLMRouter.from_config(self.config)

        self.graph = GraphStore()
        self.assumption_extractor = AssumptionExtractor()
        self.claim_analyzer = ClaimAnalyzer()
        self.claim_normalizer = ClaimNormalizer()
        self.question_generator = QuestionGenerator()
        self.quality_judge = QualityJudge()
        self.security_governor = SecurityGovernor()
        self.spam_guard = SpamGuard()
        self.novelty_scorer = NoveltyScorer(self.graph)
        self.budget = BudgetController(max_total_nodes=int(self.config["max_total_nodes"]))
        self.termination = TerminationEngine(self.config)
        self.node_factory = NodeFactory(self.claim_analyzer)
        self.evaluator = ClaimEvaluator(consensus_strategy=self.config.get("consensus_strategy", "majority"))
        self.memory_state = self.memory_store.hydrate_graph(self.graph) if self.memory_store is not None else {}
        self.debug_stats: dict[str, int | float] = {
            "run_question_duplicates_blocked": 0,
            "memory_question_repeats_degraded": 0,
            "run_claim_duplicates_blocked": 0,
            "memory_claim_repeats_degraded": 0,
            "spam_questions_filtered": 0,
            "spam_claims_filtered": 0,
            "focus_branch_hits": 0,
            "focus_branch_misses": 0,
        }

    def run(
        self,
        objective: str,
        focus_branch: str | None = None,
        on_progress: Callable[[str, int, int], None] | None = None,
    ):
        run_start = time.perf_counter()
        metrics = PhaseMetrics()
        self.termination.set_deadline(
            run_start,
            max_run_seconds=float(self.config.get("max_run_seconds", 0.0)),
            max_expand_seconds=float(self.config.get("max_expand_seconds", 0.0)),
        )
        self.debug.trace("orchestrator_start", f"run() objective={objective[:60]}", {
            "focus_branch": focus_branch,
            "mode": self._compressed.mode,
            "max_depth": self.config.get("max_depth"),
        })

        focus_claim = None
        focus_question = None
        if focus_branch:
            focus_claim, focus_question = FocusBranchResolver.resolve(focus_branch, self.memory_state)

        with metrics.context("decompose"):
            if focus_branch and focus_claim:
                root_nodes = [
                    self.node_factory.make_node(
                        id="focus-root",
                        claim=focus_claim,
                        depth=0,
                        branch_path=focus_branch,
                        source_question=focus_question,
                    )
                ]
                self.debug_stats["focus_branch_hits"] += 1
                self.debug.trace("focus_branch", f"Hit {focus_branch}", {"claim": focus_claim[:60]})
            else:
                if focus_branch:
                    self.debug_stats["focus_branch_misses"] += 1
                    self.debug.trace("focus_branch", f"Miss {focus_branch} — falling back to full scan")
                raw_root_claims = [claim for claim in self.decomposer.decompose(objective) if self.claim_normalizer.is_viable(claim)]
                root_claims = self.spam_guard.filter_claims(list(dict.fromkeys(raw_root_claims)))
                self.debug_stats["spam_claims_filtered"] += max(0, len(raw_root_claims) - len(root_claims))
                self.debug.trace("decompose", f"{len(root_claims)} root claims from objective", {
                    "raw_count": len(raw_root_claims),
                    "filtered_count": len(root_claims),
                })

                # Peer-review root claims via agent consensus
                approved = self.evaluator.filter_approved(root_claims, min_confidence=0.5)
                self.debug.trace("consensus", f"{len(approved)}/{len(root_claims)} claims approved by agent panel")

                approved_claims = [claim for claim, _ in approved] if approved else root_claims[:5]
                root_nodes = [
                    self.node_factory.make_node(
                        id=f"root-{i}",
                        claim=claim,
                        depth=0,
                        branch_path=make_branch_path("x", i),
                    )
                    for i, claim in enumerate(approved_claims)
                ]
                root_nodes.sort(key=lambda n: n.claim_priority, reverse=True)

        if on_progress:
            on_progress("decompose", 1, 1)

        total_roots = len(root_nodes)
        for idx, node in enumerate(root_nodes):
            self.graph.add_node(node)
            self.budget.consume_node()
            self._expand(node, on_progress=on_progress, current_root=idx, total_roots=total_roots)
            if on_progress:
                on_progress("expand", idx + 1, total_roots)

        with metrics.context("synthesize"):
            composer = ReportComposer(
                graph=self.graph,
                telemetry=self.telemetry,
                debug=self.debug,
                compressed=self._compressed,
                memory_store=self.memory_store,
            )
            report = composer.compose(
                objective=objective,
                synthesizer=self.synthesizer,
                focus_branch=focus_branch,
                focus_claim=focus_claim,
                debug_stats=self.debug_stats,
            )
        report.phase_metrics = metrics.to_dict()

        if on_progress:
            on_progress("complete", self.graph.size(), self.graph.size())
        return report

    def _expand(
        self,
        node: ResearchNode,
        on_progress: Callable[[str, int, int], None] | None = None,
        current_root: int = 0,
        total_roots: int = 0,
    ) -> None:
        self.debug.trace("expand_enter", f"Expanding {node.id}", {
            "branch": node.branch_path,
            "depth": node.depth,
            "claim": node.claim[:60],
        })

        stop = self.termination.should_stop_before_expansion(node, self.budget)
        if stop is not None:
            node.status = NodeStatus.STOPPED
            node.stop_reason = stop
            self.debug.trace("expand_stop", f"Pre-expansion stop: {stop}", {"node": node.id})
            return

        validation = self.validator.validate(node.claim)
        node.evidence_for = validation.get("evidence_for", [])
        node.evidence_against = validation.get("evidence_against", [])
        node.assumptions = validation.get("assumptions", []) or self.assumption_extractor.extract(node.claim)
        node.risk = float(validation.get("risk", 0.4))
        self.debug.trace("validate", f"Validated {node.id}", {
            "evidence_for": len(node.evidence_for),
            "evidence_against": len(node.evidence_against),
            "risk": node.risk,
        })

        node = must_search_counter_evidence(node)
        node.confidence = score_confidence(
            evidence_for_count=len(node.evidence_for),
            evidence_against_count=len(node.evidence_against),
        )
        node = downgrade_if_unsupported(node)

        node.questions = self.question_generator.generate(node.claim, node.assumptions)
        enforce_four_question_types(node.questions)

        node.security = self.security_governor.review(node)
        node.quality = self.quality_judge.evaluate(node)

        stop = self.termination.should_stop_after_scoring(node)
        if stop is not None:
            node.status = NodeStatus.STOPPED
            node.stop_reason = stop
            return

        fresh_questions = []
        for question in node.questions:
            if self.graph.has_similar_question(question.text):
                self.debug_stats["run_question_duplicates_blocked"] += 1
                continue
            if self.spam_guard.is_low_value_question(question.text, node.claim):
                self.debug_stats["spam_questions_filtered"] += 1
                continue
            if self.graph.has_memory_question(question.text):
                self.debug_stats["memory_question_repeats_degraded"] += 1
            question.novelty = self.novelty_scorer.score_question(question.text)
            question.priority = score_question_priority(
                impact=question.impact,
                uncertainty=question.uncertainty,
                risk=question.risk,
                novelty=question.novelty,
            )
            self.graph.register_question(question.text)
            fresh_questions.append(question)

        if not fresh_questions:
            node.status = NodeStatus.STOPPED
            node.stop_reason = StopReason.DUPLICATE_BRANCH
            return

        selected_questions = sorted(fresh_questions, key=lambda q: q.priority, reverse=True)[: int(self.config["top_k_questions"])]
        self.debug.trace("questions_selected", f"Node {node.id}", {"selected": len(selected_questions), "fresh": len(fresh_questions)})

        child_counter = 0
        total_children = 0
        for idx, question in enumerate(selected_questions):
            if self.budget.exhausted:
                node.status = NodeStatus.STOPPED
                node.stop_reason = StopReason.BUDGET_EXHAUSTED
                self.debug.trace("budget_exhausted", f"Node {node.id} — mid-expansion")
                return

            raw_child_claims = self.decomposer.decompose(question.text)
            child_claims = [claim for claim in raw_child_claims if self.claim_normalizer.is_viable(claim)]
            deduped_claims = list(dict.fromkeys(child_claims))
            filtered_claims = self.spam_guard.filter_claims(deduped_claims, parent_claim=node.claim)
            self.debug_stats["spam_claims_filtered"] += max(0, len(deduped_claims) - len(filtered_claims))
            if not filtered_claims:
                continue

            child_nodes = []
            for j, child_claim in enumerate(filtered_claims):
                branch_path = make_branch_path(node.branch_path, child_counter)
                child_counter += 1
                child_nodes.append(
                    self.node_factory.make_node(
                        id=f"{node.id}-{idx}-{j}",
                        claim=child_claim,
                        parent_ids=[node.id],
                        depth=node.depth + 1,
                        branch_path=branch_path,
                        source_question=question.text,
                    )
                )
            child_nodes.sort(key=lambda n: n.claim_priority, reverse=True)

            for child in child_nodes:
                if self.budget.exhausted:
                    node.status = NodeStatus.STOPPED
                    node.stop_reason = StopReason.BUDGET_EXHAUSTED
                    self.debug.trace("budget_exhausted", f"Node {node.id} — child creation")
                    return
                if self.graph.has_similar_claim(child.claim):
                    self.debug_stats["run_claim_duplicates_blocked"] += 1
                    continue
                if self.graph.has_memory_claim(child.claim):
                    self.debug_stats["memory_claim_repeats_degraded"] += 1
                child.novelty = self.novelty_scorer.score_node(child)
                self.graph.add_node(child)
                self.budget.consume_node()
                total_children += 1
                self._expand(child, on_progress=on_progress, current_root=current_root, total_roots=total_roots)
                if on_progress and total_roots > 0:
                    on_progress("expand", current_root + 1, total_roots)

        node.status = NodeStatus.EXPANDED
        self.debug.trace("expand_exit", f"Node {node.id} expanded", {
            "children_created": total_children,
            "depth": node.depth,
        })
