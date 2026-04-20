from app.models.enums import NodeStatus
from app.models.report import FinalReport


class Synthesizer:
    def synthesize(self, objective: str, nodes):
        report = FinalReport(objective=objective)
        seen_assumptions = set()
        seen_support = set()
        seen_oppose = set()
        seen_unresolved = set()

        sorted_nodes = sorted(nodes, key=lambda n: n.claim_priority, reverse=True)

        for node in sorted_nodes:
            report.confidence_map[node.claim] = node.confidence
            report.claim_types[node.claim] = node.claim_type.value
            report.claim_priorities[node.claim] = round(node.claim_priority, 4)
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
                f"[{node.claim_type.value}] {node.claim} -> risk={node.risk:.2f} priority={node.claim_priority:.2f}"
            )
            if node.status == NodeStatus.STOPPED and node.stop_reason:
                report.stopped_branches.append(f"{node.claim} -> {node.stop_reason.value}")

        report.main_findings = [node.claim for node in sorted_nodes[:10]]
        report.key_risks = list(dict.fromkeys(report.key_risks))
        return report
