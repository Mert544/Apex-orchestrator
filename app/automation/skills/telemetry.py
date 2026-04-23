from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.automation.models import AutomationContext
from app.execution.token_telemetry import TokenTelemetry

from ._context import _target_root


def record_telemetry_skill(context: AutomationContext):
    """Record token telemetry for the current run state."""
    telemetry = TokenTelemetry(budget_limit=int(context.config.get("token_budget_limit", 0)))
    # Replay known state into telemetry
    for key in context.state:
        val = context.state[key]
        if isinstance(val, dict):
            telemetry.record_skill_call(key, input_text=str(val), output_text=str(val))
        elif isinstance(val, str):
            telemetry.record_skill_call(key, input_text=val, output_text=val)
    snap = telemetry.snapshot()
    context.state["telemetry"] = snap.to_dict()
    return snap.to_dict()


def export_token_report_skill(context: AutomationContext):
    """Export a JSON token report to .apex/telemetry/ directory."""
    target_root = _target_root(context)
    telemetry_data = context.state.get("telemetry", {})
    if not telemetry_data:
        telemetry_data = record_telemetry_skill(context)

    apex_dir = Path(target_root) / ".apex" / "telemetry"
    apex_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = apex_dir / f"run-{run_id}.json"
    report = {
        "run_id": run_id,
        "objective": context.objective,
        "telemetry": telemetry_data,
        "state_keys": list(context.state.keys()),
    }
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    result_dict = {
        "ok": True,
        "report_path": str(report_path),
        "run_id": run_id,
    }
    context.state["token_report"] = result_dict
    return result_dict
