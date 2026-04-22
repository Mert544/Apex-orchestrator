from pathlib import Path

from app.engine.token_accounting import TokenAccounting
from app.models.enums import NodeStatus
from app.models.report import FinalReport
from app.skills.action_generator import ActionGenerator
from app.tools.project_profile import ProjectProfiler


class Synthesizer:
    def __init__(self, project_root: str | Path | None = None) -> None:
        self.action_generator = ActionGenerator()
        self.project_root = Path(project_root) if project_root is not None else None
        self.token_accounting = TokenAccounting()

    def synthesize(self, objective: str, nodes):
        report = FinalReport(objective=objective)
        seen_assumptions = set()
        seen_support = set()
        seen_oppose = set()
        seen_unresolved = set()
        seen_findings = set()

        sorted_nodes = sorted(nodes, key=lambda n: n.claim_priority, reverse=True)

        for node in sorted_nodes:
            report.confidence_map[node.claim] = node.confidence
            report.claim_types[node.claim] = node.claim_type.value
            report.claim_priorities[node.claim] = round(node.claim_priority, 4)
            report.branch_map[node.branch_path] = node.claim
            if node.source_question:
                report.branch_questions[node.branch_path] = node.source_question
            for assumption in node.assumptions:
                if assumption not in seen_assumptions:
                    seen_assumptions.add(assumption)
                    report.assumptions.append(assumption)
            for evidence in node.evidence_for:
                if evidence not in seen_support:
                    seen_support.add(evidence)
                    report.strongest_supporting_evidence.append(evidence)
            for evidence in node.evidence_against:
                if evidence not in seen_oppose:
                    seen_oppose.add(evidence)
                    report.strongest_opposing_evidence.append(evidence)
            for question in node.questions:
                if question.text not in seen_unresolved:
                    seen_unresolved.add(question.text)
                    report.unresolved_questions.append(question.text)
            report.key_risks.append(
                f"[{node.branch_path}] [{node.claim_type.value}] {node.claim} -> risk={node.risk:.2f} priority={node.claim_priority:.2f}"
            )
            if node.status == NodeStatus.STOPPED and node.stop_reason:
                report.stopped_branches.append(f"{node.branch_path} {node.claim} -> {node.stop_reason.value}")
            if node.claim not in seen_findings and len(report.main_findings) < 10:
                seen_findings.add(node.claim)
                report.main_findings.append(node.claim)

        report.key_risks = list(dict.fromkeys(report.key_risks))
        profile = None
        if self.project_root is not None and self.project_root.exists():
            profile = ProjectProfiler(self.project_root).profile()
        report.recommended_actions = self.action_generator.generate(sorted_nodes, profile=profile)

        analysis_texts = [objective]
        analysis_texts.extend(report.branch_map.values())
        analysis_texts.extend(report.branch_questions.values())
        analysis_texts.extend(report.assumptions)
        analysis_texts.extend(report.strongest_supporting_evidence)
        analysis_texts.extend(report.strongest_opposing_evidence)
        analysis_texts.extend(report.unresolved_questions)

        response_texts = []
        response_texts.extend(report.main_findings)
        response_texts.extend(report.key_risks)
        response_texts.extend(report.recommended_actions)
        response_texts.extend(report.stopped_branches)

        report.estimated_analysis_tokens = self.token_accounting.estimate_many(analysis_texts)
        report.estimated_response_tokens = self.token_accounting.estimate_many(response_texts)
        report.estimated_memory_tokens = 0
        report.estimated_total_tokens = report.estimated_analysis_tokens + report.estimated_response_tokens
        return report
