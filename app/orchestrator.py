from __future__ import annotations

from typing import Any

from app.engine.budget import BudgetController
from app.engine.execution_loop import ExecutionLoop
from app.engine.novelty import NoveltyScorer
from app.engine.termination import TerminationEngine
from app.memory.graph_store import GraphStore
from app.models.enums import NodeStatus, StopReason
from app.models.node import ResearchNode
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
    def __init__(self, config: dict[str, Any], decomposer, validator, synthesizer, memory_store=None) -> None:
        self.config = config
        self.decomposer = decomposer
        self.validator = validator
        self.synthesizer = synthesizer
        self.memory_store = memory_store

        self.graph = GraphStore()
        self.assumption_extractor = AssumptionExtractor()
        self.claim_analyzer = ClaimAnalyzer()
        self.claim_normalizer = ClaimNormalizer()
        self.question_generator = QuestionGenerator()
        self.quality_judge = QualityJudge()
        self.security_governor = SecurityGovernor()
        self.spam_guard = SpamGuard()
        self.novelty_scorer = NoveltyScorer(self.graph)
        self.budget = BudgetController(max_total_nodes=int(config["max_total_nodes"]))
        self.termination = TerminationEngine(config)
        self.execution_loop = ExecutionLoop()
        self.memory_state = self.memory_store.hydrate_graph(self.graph) if self.memory_store is not None else {}

    def run(self, objective: str):
        root_claims = [claim for claim in self.decomposer.decompose(objective) if self.claim_normalizer.is_viable(claim)]
        root_claims = self.spam_guard.filter_claims(list(dict.fromkeys(root_claims)))
        root_nodes = [
            self._make_node(
                id=f"root-{i}",
                claim=claim,
                depth=0,
                branch_path=make_branch_path("x", i),
            )
            for i, claim in enumerate(root_claims)
        ]
        root_nodes.sort(key=lambda n: n.claim_priority, reverse=True)

        for node in root_nodes:
            self.graph.add_node(node)
            self.budget.consume_node()
            self._expand(node)

        report = self.synthesizer.synthesize(objective, self.graph.get_all_nodes())
        if self.memory_store is not None:
            memory_summary = self.memory_store.persist_run(objective, report, self.graph.get_all_nodes())
            report.memory_file = memory_summary.get("memory_file")
            report.memory_run_id = memory_summary.get("run_id")
            report.known_claim_count = memory_summary.get("known_claim_count", 0)
            report.known_question_count = memory_summary.get("known_question_count", 0)
            report.previous_run_count = memory_summary.get("previous_run_count", 0)
        return report

    def _make_node(
        self,
        id: str,
        claim: str,
        depth: int,
        parent_ids: list[str] | None = None,
        branch_path: str = "",
        source_question: str | None = None,
    ) -> ResearchNode:
        analysis = self.claim_analyzer.analyze(claim)
        return ResearchNode(
            id=id,
            claim=claim,
            parent_ids=parent_ids or [],
            depth=depth,
            branch_path=branch_path,
            source_question=source_question,
            claim_type=analysis.claim_type,
            claim_priority=analysis.priority,
            claim_signals=analysis.signals,
        )

    def _expand(self, node: ResearchNode) -> None:
        stop = self.termination.should_stop_before_expansion(node, self.budget)
        if stop is not None:
            node.status = NodeStatus.STOPPED
            node.stop_reason = stop
            return

        validation = self.validator.validate(node.claim)
        node.evidence_for = validation.get("evidence_for", [])
        node.evidence_against = validation.get("evidence_against", [])
        node.assumptions = validation.get("assumptions", []) or self.assumption_extractor.extract(node.claim)
        node.risk = float(validation.get("risk", 0.4))

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
        node.novelty = self.novelty_scorer.score_node(node)

        stop = self.termination.should_stop_after_scoring(node)
        if stop is not None:
            node.status = NodeStatus.STOPPED
            node.stop_reason = stop
            return

        fresh_questions = []
        for question in node.questions:
            if self.graph.has_similar_question(question.text):
                continue
            if self.spam_guard.is_low_value_question(question.text, node.claim):
                continue
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

        child_counter = 0
        for idx, question in enumerate(selected_questions):
            if self.budget.exhausted:
                node.status = NodeStatus.STOPPED
                node.stop_reason = StopReason.BUDGET_EXHAUSTED
                return

            raw_child_claims = self.decomposer.decompose(question.text)
            child_claims = [claim for claim in raw_child_claims if self.claim_normalizer.is_viable(claim)]
            child_claims = self.spam_guard.filter_claims(list(dict.fromkeys(child_claims)), parent_claim=node.claim)
            if not child_claims:
                continue

            child_nodes = []
            for j, child_claim in enumerate(child_claims):
                branch_path = make_branch_path(node.branch_path, child_counter)
                child_counter += 1
                child_nodes.append(
                    self._make_node(
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
                    return
                if self.graph.has_similar_claim(child.claim):
                    continue
                self.graph.add_node(child)
                self.budget.consume_node()
                self.execution_loop.expand(self, child)

        node.status = NodeStatus.EXPANDED
