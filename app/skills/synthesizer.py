from pathlib import Path

from app.engine.token_accounting import TokenAccounting
from app.models.enums import NodeStatus
from app.models.report import FinalReport
from app.skills.action_generator import ActionGenerator
from app.tools.project_profile import ProjectProfiler


def _append_new(seen, target, items) -> None:
    for item in items:
        if item not in seen:
            seen.add(item)
            target.append(item)


def _accumulate_node(report: FinalReport, node, seen) -> None:
    report.confidence_map[node.claim] = node.confidence
    report.claim_types[node.claim] = node.claim_type.value
    report.claim_priorities[node.claim] = round(node.claim_priority, 4)
    report.branch_map[node.branch_path] = node.claim
    if node.source_question:
        report.branch_questions[node.branch_path] = node.source_question
    _append_new(seen["assumptions"], report.assumptions, node.assumptions)
    _append_new(seen["support"], report.strongest_supporting_evidence, node.evidence_for)
    _append_new(seen["oppose"], report.strongest_opposing_evidence, node.evidence_against)
    _append_new(seen["unresolved"], report.unresolved_questions, (q.text for q in node.questions))
    report.key_risks.append(
        f"[{node.branch_path}] [{node.claim_type.value}] {node.claim} -> risk={node.risk:.2f} priority={node.claim_priority:.2f}"
    )
    if node.status == NodeStatus.STOPPED and node.stop_reason:
        report.stopped_branches.append(f"{node.branch_path} {node.claim} -> {node.stop_reason.value}")
    if node.claim not in seen["findings"] and len(report.main_findings) < 10:
        seen["findings"].add(node.claim)
        report.main_findings.append(node.claim)


def _analysis_texts(objective: str, report: FinalReport) -> list:
    texts = [objective]
    texts.extend(report.branch_map.values())
    texts.extend(report.branch_questions.values())
    texts.extend(report.assumptions)
    texts.extend(report.strongest_supporting_evidence)
    texts.extend(report.strongest_opposing_evidence)
    texts.extend(report.unresolved_questions)
    return texts


def _response_texts(report: FinalReport) -> list:
    texts = []
    texts.extend(report.main_findings)
    texts.extend(report.key_risks)
    texts.extend(report.recommended_actions)
    texts.extend(report.stopped_branches)
    return texts


class Synthesizer:
    def __init__(self, project_root: str | Path | None = None) -> None:
        self.action_generator = ActionGenerator()
        self.project_root = Path(project_root) if project_root is not None else None
        self.token_accounting = TokenAccounting()

    def synthesize(self, objective: str, nodes):
        report = FinalReport(objective=objective)
        seen = {key: set() for key in ("assumptions", "support", "oppose", "unresolved", "findings")}

        sorted_nodes = sorted(nodes, key=lambda n: n.claim_priority, reverse=True)
        for node in sorted_nodes:
            _accumulate_node(report, node, seen)

        report.key_risks = list(dict.fromkeys(report.key_risks))
        profile = None
        if self.project_root is not None and self.project_root.exists():
            profile = ProjectProfiler(self.project_root).profile()
        report.recommended_actions = self.action_generator.generate(sorted_nodes, profile=profile)

        report.estimated_analysis_tokens = self.token_accounting.estimate_many(_analysis_texts(objective, report))
        report.estimated_response_tokens = self.token_accounting.estimate_many(_response_texts(report))
        report.estimated_memory_tokens = 0
        report.estimated_total_tokens = report.estimated_analysis_tokens + report.estimated_response_tokens
        return report
