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
from app.skills.question_generator import QuestionGenerator
from app.skills.quality_judge import QualityJudge
from app.skills.security_governor import SecurityGovernor


class FractalResearchOrchestrator:
    def __init__(self, config: dict[str, Any], decomposer, validator, synthesizer) -> None:
        self.config = config
        self.decomposer = decomposer
        self.validator = validator
        self.synthesizer = synthesizer

        self.graph = GraphStore()
        self.assumption_extractor = AssumptionExtractor()
        self.claim_analyzer = ClaimAnalyzer()
        self.question_generator = QuestionGenerator()
        self.quality_judge = QualityJudge()
        self.security_governor = SecurityGovernor()
        self.novelty_scorer = NoveltyScorer(self.graph)
        self.budget = BudgetController(max_total_nodes=int(config["max_total_nodes"]))
        self.termination = TerminationEngine(config)
        self.execution_loop = ExecutionLoop()

    def run(self, objective: str):
        root_claims = self.decomposer.decompose(objective)
        root_nodes = [self._make_node(id=f"root-{i}", claim=claim, depth=0) for i, claim in enumerate(root_claims)]
        root_nodes.sort(key=lambda n: n.claim_priority, reverse=True)

        for node in root_nodes:
            self.graph.add_node(node)
            self.budget.consume_node()
            self._expand(node)
        return self.synthesizer.synthesize(objective, self.graph.get_all_nodes())

    def _make_node(self, id: str, claim: str, depth: int, parent_ids: list[str] | None = None) -> ResearchNode:
        analysis = self.claim_analyzer.analyze(claim)
        return ResearchNode(
            id=id,
            claim=claim,
            parent_ids=parent_ids or [],
            depth=depth,
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

        for idx, question in enumerate(selected_questions):
            if self.budget.exhausted:
                node.status = NodeStatus.STOPPED
                node.stop_reason = StopReason.BUDGET_EXHAUSTED
                return

            child_claims = self.decomposer.decompose(question.text)
            child_nodes = [
                self._make_node(
                    id=f"{node.id}-{idx}-{j}",
                    claim=child_claim,
                    parent_ids=[node.id],
                    depth=node.depth + 1,
                )
                for j, child_claim in enumerate(child_claims)
            ]
            child_nodes.sort(key=lambda n: n.claim_priority, reverse=True)

            for child in child_nodes:
                if self.budget.exhausted:
                    node.status = NodeStatus.STOPPED
                    node.stop_reason = StopReason.BUDGET_EXHAUSTED
                    return
                self.graph.add_node(child)
                self.budget.consume_node()
                self.execution_loop.expand(self, child)

        node.status = NodeStatus.EXPANDED
