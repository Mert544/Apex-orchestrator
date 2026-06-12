"""Proof-of-Fix — a machine-readable evidence record for every applied fix.

A maintenance pass should not just *say* it verified its fixes; it should hand
over the evidence. This module turns an ``apply_plan`` summary into a
self-contained JSON artifact: for each fix, the finding it cites, the exact
unified diff applied, the test run that verified it (commands, pass/fail
counts, duration), and any rollback that occurred. A reviewer — or a
compliance pipeline — can open the artifact and audit the pass without
trusting a single prose claim.

The record describes a real run, so it carries measured durations and a
timestamp; nothing here feeds back into scoring (determinism of the engine's
reasoning is untouched).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "apex-proof-of-fix"
SCHEMA_VERSION = "1.0"

_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) error")


def tool_version() -> str:
    """Installed package version, best-effort (never raises)."""
    try:
        from importlib.metadata import version

        return version("apex-orchestrator")
    except Exception:
        return "unknown"


def summarize_test_run(summary: Any) -> dict:
    """Distill a :class:`TestRunSummary` into auditable verification evidence.

    Parses pytest's tail counts ("N passed", "N failed") out of the captured
    output and totals the measured duration — enough for a reviewer to see
    *what* verified the fix and *how thoroughly*, without storing megabytes
    of raw logs.
    """
    passed = failed = errors = 0
    duration = 0.0
    for res in getattr(summary, "results", None) or []:
        text = (res.get("stdout") or "") + (res.get("stderr") or "")
        for pattern, bump in ((_PASSED, "p"), (_FAILED, "f"), (_ERRORS, "e")):
            m = pattern.search(text)
            if not m:
                continue
            n = int(m.group(1))
            if bump == "p":
                passed += n
            elif bump == "f":
                failed += n
            else:
                errors += n
        duration += float(res.get("duration_seconds") or 0.0)
    return {
        "performed": bool(getattr(summary, "commands", None)),
        "strategy": "full-suite",
        "ok": bool(getattr(summary, "ok", False)),
        "commands": [list(c) for c in (getattr(summary, "commands", None) or [])],
        "tests_passed": passed,
        "tests_failed": failed,
        "errors": errors,
        "duration_seconds": round(duration, 3),
    }


def _fix_record(r: dict) -> dict:
    """One per-step evidence record from an ``apply_plan`` result row."""
    if r.get("rolled_back"):
        outcome = "rolled_back"
    elif r.get("applied"):
        outcome = "applied"
    else:
        outcome = "blocked"
    verification = dict(r.get("test_evidence") or {"performed": False})
    if r.get("verification_strength"):
        # Coverage-aware honesty: a green suite that never references the
        # changed module is recorded as exactly that.
        verification["strength"] = r["verification_strength"]
    record = {
        "finding": {
            "label": r.get("label", ""),
            "branch": r.get("branch", ""),
            "action": r.get("action", ""),
            "operator": r.get("operator", ""),
            "target": r.get("target", ""),
        },
        "transform_type": r.get("transform_type", ""),
        "risk_tier": r.get("risk_tier", None),
        "outcome": outcome,
        "changed_files": r.get("changed_files") or [],
        "diff": r.get("diff", ""),
        "verification": verification,
        "rollback": {
            "occurred": bool(r.get("rolled_back")),
            "reason": r.get("reason", "") if r.get("rolled_back") else "",
        },
    }
    if r.get("commit_hash"):
        record["commit_hash"] = r["commit_hash"]
    if r.get("shield_test"):
        # Test-first: the characterization test generated to protect this fix.
        record["shield_test"] = r["shield_test"]
    if r.get("converged_fixes"):
        record["converged_fixes"] = r["converged_fixes"]
    if outcome == "blocked" and r.get("reason"):
        record["blocked_reason"] = r["reason"]
    return record


def build_proof(summary: dict, project_root: str, objective: str = "") -> dict:
    """Assemble the full proof artifact from an ``apply_plan`` summary."""
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "Apex Orchestrator", "version": tool_version()},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "objective": objective,
        "mode": summary.get("mode", ""),
        "verify": bool(summary.get("verify")),
        "totals": {
            "executable": summary.get("total_executable", 0),
            "applied": summary.get("applied", 0),
            "rolled_back": summary.get("rolled_back", 0),
            "blocked": summary.get("blocked", 0),
            "committed": summary.get("committed", 0),
        },
        "fixes": [_fix_record(r) for r in summary.get("results", [])],
    }


def write_proof(proof: dict, project_root: str, out: str | Path | None = None) -> Path:
    """Write the artifact (default: ``.apex/proof-of-fix.json``) and return its path."""
    path = Path(out) if out else Path(project_root) / ".apex" / "proof-of-fix.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return path
