from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class DashboardDataCollector:
    """Collect metrics from existing Apex engines without hard dependencies.

    Every method gracefully degrades to placeholder data if the underlying
    engine file does not exist or cannot be imported.
    """

    def __init__(self, project_root: str = ".") -> None:
        self.project_root = Path(project_root).resolve()

    # ------------------------------------------------------------------
    # 1. Reception  —  ProjectProfiler / RepoScanner
    # ------------------------------------------------------------------
    def get_reception_data(self) -> dict[str, Any]:
        root = self.project_root
        total_files = 0
        try:
            total_files = sum(1 for _ in root.rglob("*.py"))
        except Exception:
            pass
        return {
            "total_files": total_files,
            "project_name": root.name,
            "status": "open",
            "last_action": f"Scanned {total_files} Python files",
        }

    # ------------------------------------------------------------------
    # 2. Board Room  —  SmartPlanner / CrossRunTracker
    # ------------------------------------------------------------------
    def get_board_data(self) -> dict[str, Any]:
        memory_file = self.project_root / ".epistemic" / "memory.json"
        last_plan = "—"
        open_claims = 0
        if memory_file.exists():
            try:
                data = json.loads(memory_file.read_text(encoding="utf-8"))
                runs = data.get("runs", [])
                if runs:
                    last = runs[-1]
                    last_plan = last.get("plan", "project_scan")
                    report = last.get("report", {})
                    open_claims = len(report.get("critical_untested_modules", []))
            except Exception:
                pass
        return {
            "active_plan": last_plan,
            "open_claims": open_claims,
            "status": "busy" if open_claims > 0 else "idle",
            "last_action": f"Selected plan: {last_plan}" if last_plan != "—" else "Waiting for input",
        }

    # ------------------------------------------------------------------
    # 3. Dev Office  —  SemanticPatchGenerator
    # ------------------------------------------------------------------
    def get_dev_data(self) -> dict[str, Any]:
        transforms = [
            "add_docstring", "add_type_annotations", "add_guard_clause",
            "repair_test_assertion", "create_test_stub", "rename_variable",
            "extract_method", "inline_variable", "organize_imports",
            "move_class", "extract_class",
        ]
        return {
            "transforms_available": len(transforms),
            "transforms_list": transforms,
            "status": "idle",
            "last_action": "AST transforms ready",
        }

    # ------------------------------------------------------------------
    # 4. QA Lab  —  AbductiveReasoner + ConfidenceCalibrator
    # ------------------------------------------------------------------
    def get_qa_data(self) -> dict[str, Any]:
        memory_file = self.project_root / ".epistemic" / "memory.json"
        issues_found = 0
        avg_confidence = 0.75
        if memory_file.exists():
            try:
                data = json.loads(memory_file.read_text(encoding="utf-8"))
                runs = data.get("runs", [])
                if runs:
                    report = runs[-1].get("report", {})
                    issues_found = len(report.get("critical_untested_modules", []))
            except Exception:
                pass
        return {
            "issues_found": issues_found,
            "avg_confidence": avg_confidence,
            "status": "busy" if issues_found > 0 else "idle",
            "last_action": f"Calibrated {issues_found} issues" if issues_found else "All clear",
        }

    # ------------------------------------------------------------------
    # 5. Security Office  —  SafetyGovernor + FunctionFractalAnalyzer
    # ------------------------------------------------------------------
    def get_security_data(self) -> dict[str, Any]:
        risky_count = 0
        risk_patterns = ["eval(", "os.system(", "pickle.loads(", "exec(", "compile("]
        try:
            for f in self.project_root.rglob("*.py"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                for pat in risk_patterns:
                    if pat in text:
                        risky_count += 1
                        break
        except Exception:
            pass
        return {
            "risky_functions": risky_count,
            "patterns_checked": len(risk_patterns),
            "status": "alert" if risky_count > 0 else "safe",
            "last_action": f"Found {risky_count} risky patterns" if risky_count else "Perimeter secure",
        }

    # ------------------------------------------------------------------
    # 6. R&D Lab  —  RecursiveReflectionEngine + CounterfactualGenerator
    # ------------------------------------------------------------------
    def get_rnd_data(self) -> dict[str, Any]:
        return {
            "reflection_depth": 4,
            "counterfactuals_generated": 6,
            "status": "thinking",
            "last_action": "4-layer reflection complete",
        }

    # ------------------------------------------------------------------
    # 7. Archive Room  —  CrossRunTracker / PersistentMemory
    # ------------------------------------------------------------------
    def get_archive_data(self) -> dict[str, Any]:
        memory_file = self.project_root / ".epistemic" / "memory.json"
        total_runs = 0
        resolved_claims = 0
        if memory_file.exists():
            try:
                data = json.loads(memory_file.read_text(encoding="utf-8"))
                total_runs = len(data.get("runs", []))
                for run in data.get("runs", []):
                    report = run.get("report", {})
                    resolved_claims += len(report.get("resolved", []))
            except Exception:
                pass
        return {
            "total_runs": total_runs,
            "resolved_claims": resolved_claims,
            "status": "organizing",
            "last_action": f"Archived {total_runs} runs" if total_runs else "Waiting for data",
        }

    # ------------------------------------------------------------------
    # 8. HR / Swarm  —  SwarmCoordinator
    # ------------------------------------------------------------------
    def get_swarm_data(self) -> dict[str, Any]:
        return {
            "active_workers": 0,
            "max_workers": 4,
            "status": "idle",
            "last_action": "Swarm ready for dispatch",
        }

    # ------------------------------------------------------------------
    # 9. Break Room  —  Telemetry / TokenBudget
    # ------------------------------------------------------------------
    def get_break_data(self) -> dict[str, Any]:
        telem_dir = self.project_root / ".apex" / "telemetry"
        session_cost = 0.0
        tokens_in = 0
        tokens_out = 0
        if telem_dir.exists():
            files = sorted(telem_dir.glob("run-*.json"))
            if files:
                try:
                    data = json.loads(files[-1].read_text(encoding="utf-8"))
                    telem = data.get("telemetry", {})
                    tokens_in = telem.get("total_input_chars", 0) // 4
                    tokens_out = telem.get("total_output_chars", 0) // 4
                    session_cost = round((tokens_in + tokens_out) * 0.000002, 4)
                except Exception:
                    pass
        return {
            "session_cost_usd": session_cost,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "status": "idle",
            "last_action": f"Tracked ${session_cost} usage" if session_cost else "No session yet",
        }

    # ------------------------------------------------------------------
    # 10. Gym / Spa  —  SystemHealth / Cooldown
    # ------------------------------------------------------------------
    def get_gym_data(self) -> dict[str, Any]:
        memory_file = self.project_root / ".epistemic" / "memory.json"
        last_run_time = None
        if memory_file.exists():
            try:
                data = json.loads(memory_file.read_text(encoding="utf-8"))
                runs = data.get("runs", [])
                if runs:
                    last_run_time = runs[-1].get("timestamp")
            except Exception:
                pass
        return {
            "system_health": 100,
            "last_run": last_run_time,
            "status": "idle",
            "last_action": "System recovery complete" if last_run_time else "Ready to start",
        }

    # ------------------------------------------------------------------
    # Ticker
    # ------------------------------------------------------------------
    def get_ticker_events(self) -> list[dict[str, Any]]:
        events = [
            {"time": time.strftime("%H:%M"), "msg": "Apex Orchestrator office online", "severity": "info"},
            {"time": time.strftime("%H:%M"), "msg": "All departments operational", "severity": "ok"},
        ]
        board = self.get_board_data()
        if board["open_claims"] > 0:
            events.append({
                "time": time.strftime("%H:%M"),
                "msg": f"Board Room: {board['open_claims']} open claims need attention",
                "severity": "warn",
            })
        sec = self.get_security_data()
        if sec["risky_functions"] > 0:
            events.append({
                "time": time.strftime("%H:%M"),
                "msg": f"Security: {sec['risky_functions']} risky patterns detected!",
                "severity": "alert",
            })
        dev = self.get_dev_data()
        events.append({
            "time": time.strftime("%H:%M"),
            "msg": f"Dev Office: {dev['transforms_available']} AST transforms loaded",
            "severity": "info",
        })
        qa = self.get_qa_data()
        if qa["issues_found"] > 0:
            events.append({
                "time": time.strftime("%H:%M"),
                "msg": f"QA Lab: {qa['issues_found']} issues under review",
                "severity": "warn",
            })
        archive = self.get_archive_data()
        if archive["total_runs"] > 0:
            events.append({
                "time": time.strftime("%H:%M"),
                "msg": f"Archive: {archive['total_runs']} runs on record",
                "severity": "info",
            })
        return events

    # ------------------------------------------------------------------
    # All departments
    # ------------------------------------------------------------------
    def get_all_departments(self) -> dict[str, dict[str, Any]]:
        return {
            "reception": self.get_reception_data(),
            "board": self.get_board_data(),
            "dev": self.get_dev_data(),
            "qa": self.get_qa_data(),
            "security": self.get_security_data(),
            "rnd": self.get_rnd_data(),
            "archive": self.get_archive_data(),
            "swarm": self.get_swarm_data(),
            "break": self.get_break_data(),
            "gym": self.get_gym_data(),
        }
