from __future__ import annotations

import time
from typing import Any

from app.engine.compressed_mode import CompressedModeEngine
from app.engine.debug_engine import DebugEngine
from app.execution.token_telemetry import TokenTelemetry
from app.memory.graph_store import GraphStore
from app.models.report import FinalReport


class ReportComposer:
    """Compose the final report after graph expansion is complete."""

    def __init__(
        self,
        graph: GraphStore,
        telemetry: TokenTelemetry,
        debug: DebugEngine,
        compressed: CompressedModeEngine,
        memory_store: Any | None = None,
    ) -> None:
        self.graph = graph
        self.telemetry = telemetry
        self.debug = debug
        self.compressed = compressed
        self.memory_store = memory_store

    def compose(
        self,
        objective: str,
        synthesizer,
        focus_branch: str | None,
        focus_claim: str | None,
        debug_stats: dict[str, int | float],
    ) -> FinalReport:
        all_nodes = self.graph.get_all_nodes()

        self.debug.snapshot(
            claims=[n.model_dump() for n in all_nodes],
            branch_map=self.graph.branch_map(),
            telemetry=self.telemetry.snapshot().to_dict(),
        )

        report = synthesizer.synthesize(objective, all_nodes)
        report.focus_branch = focus_branch
        report.focus_claim = focus_claim
        report.debug_stats = dict(debug_stats)
        report.mode = self.compressed.mode

        # Record telemetry for this run
        self.telemetry.record_analysis(objective)
        self.telemetry.record_response(report.model_dump_json())

        if self.memory_store is not None:
            memory_summary = self.memory_store.persist_run(objective, report, all_nodes)
            report.memory_file = memory_summary.get("memory_file")
            report.memory_run_id = memory_summary.get("run_id")
            report.known_claim_count = memory_summary.get("known_claim_count", 0)
            report.known_question_count = memory_summary.get("known_question_count", 0)
            report.previous_run_count = memory_summary.get("previous_run_count", 0)
            report.estimated_memory_tokens = (report.known_claim_count * 8) + (report.known_question_count * 8)
            report.estimated_total_tokens = (
                report.estimated_analysis_tokens
                + report.estimated_response_tokens
                + report.estimated_memory_tokens
            )
            self.telemetry.record_memory(report.model_dump_json())

        # Attach telemetry snapshot to report
        snap = self.telemetry.snapshot()
        report.telemetry = snap.to_dict()

        # Attach debug diagnostics
        report.debug_diagnostics = self.debug.diagnose(
            claims=[n.model_dump() for n in all_nodes],
        )
        report.debug_stats = {**report.debug_stats, **self.debug._phase_breakdown()}

        # Generate debug report to disk if enabled
        if self.debug.enabled:
            debug_report = self.debug.report()
            report.debug_report_file = str(
                self.debug.project_root / ".apex" / "debug" / f"debug-{int(time.time())}.json"
            )
            self.debug.trace("orchestrator_end", f"run() complete — {len(all_nodes)} nodes")

        # Apply compressed mode report trimming if active
        if self.compressed.mode == "compressed":
            report_dict = report.model_dump()
            compressed = self.compressed.compress_report(report_dict)
            for key in ("main_findings", "branch_map", "recommended_actions", "key_risks"):
                if key in compressed:
                    setattr(report, key, compressed[key])

        return report
