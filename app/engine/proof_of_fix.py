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

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SCHEMA = "apex-proof-of-fix"
SCHEMA_VERSION = "1.0"

# A buyer/CI consumes this side-car, never the raw artifact: a stable content
# hash to pin + a manifest derived only from the records (so it can never
# disagree with them).
BUNDLE_SCHEMA = "apex-proof-bundle"
BUNDLE_VERSION = "1.0"

# The coverage levels a verified record can carry (see verification_strength);
# fixed order so the manifest's by-coverage tally is deterministic even at zero.
_COVERAGE_LEVELS = ("function", "module", "test-change", "none")

_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) error")
# pytest's short summary lines — the names a human needs to act on a failure.
_FAIL_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


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
    failures: list[str] = []
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
        failures += _FAIL_LINE.findall(text)
        duration += float(res.get("duration_seconds") or 0.0)
    return {
        "performed": bool(getattr(summary, "commands", None)),
        "strategy": "full-suite",
        "ok": bool(getattr(summary, "ok", False)),
        "commands": [list(c) for c in (getattr(summary, "commands", None) or [])],
        "tests_passed": passed,
        "tests_failed": failed,
        "errors": errors,
        # WHICH tests failed (capped): the line a human needs to act on a
        # rollback without rerunning the whole suite to find out.
        "failing_tests": failures[:5],
        "duration_seconds": round(duration, 3),
    }


def _outcome_for(r: dict) -> str:
    """Classify one ``apply_plan`` result row into a single terminal outcome.

    ``skipped_learned`` (the fix the opt-in closed loop DECLINED before any
    apply attempt) is its own outcome so it never poisons the learning signal
    as a fresh "failure"; it is only ever present when the avoid-guard was
    armed, so default proofs stay byte-identical."""
    if r.get("skipped_learned"):
        return "skipped_learned"
    if r.get("rolled_back"):
        return "rolled_back"
    if r.get("applied"):
        return "applied"
    return "blocked"


def _fix_record(r: dict) -> dict:
    """One per-step evidence record from an ``apply_plan`` result row."""
    outcome = _outcome_for(r)
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
    if r.get("impact"):
        # Proof-of-VALUE: the measured before→after metric win the apply path
        # observed (e.g. "max nesting 3→1, cognitive 6→3"). Additive — absent
        # when no metric moved, so a no-op fix's record is byte-identical.
        record["impact"] = r["impact"]
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


# --- Proof BUNDLE: tamper-evident hash + auditable manifest -----------------
#
# Additive side-car over the existing artifact. The hash is taken over the
# *meaningful content* of the per-fix records — the facts a reviewer audits —
# and nothing else: no timestamp, no tool version, no key ordering, no float
# jitter. Same fixes in → byte-identical hash out; change any recorded fact and
# the hash changes. A CI gate pins the hash; a buyer reads the manifest.


def _records_of(artifact_or_records: Any) -> list[dict]:
    """Accept either a full proof artifact or a bare ``fixes`` list."""
    if isinstance(artifact_or_records, dict):
        return list(artifact_or_records.get("fixes") or [])
    return list(artifact_or_records or [])


def _round_floats(value: Any) -> Any:
    """Recursively pin float precision so re-measured durations don't shift the
    hash on facts a human would read as identical (6 dp is well below noise)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_floats(v) for v in value]
    return value


def _hashable_record(rec: dict) -> dict:
    """The audit-meaningful projection of one record: finding, transform,
    outcome, the files + diff, the verification/coverage it claims, and the
    rollback. Optional clauses (impact, commit_hash, shield_test, …) are folded
    in only when present, so a record without them hashes byte-identically to a
    pre-bundle record. Everything outside this projection (nothing today) is
    deliberately excluded from the tamper seal."""
    out: dict = {
        "finding": rec.get("finding", {}),
        "transform_type": rec.get("transform_type", ""),
        "risk_tier": rec.get("risk_tier", None),
        "outcome": rec.get("outcome", ""),
        "changed_files": list(rec.get("changed_files") or []),
        "diff": rec.get("diff", ""),
        "verification": rec.get("verification", {}),
        "rollback": rec.get("rollback", {}),
    }
    for opt in ("impact", "commit_hash", "shield_test", "converged_fixes",
                "blocked_reason"):
        if opt in rec:
            out[opt] = rec[opt]
    return _round_floats(out)


def _canonical_json(value: Any) -> str:
    """Sorted-key, no-whitespace JSON — the one canonical byte form to hash."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def proof_hash(artifact_or_records: Any) -> str:
    """A deterministic ``sha256:<hex>`` over the records' meaningful content.

    Byte-identical for the same recorded fixes across runs/machines; changes if
    any audited fact (finding, diff, outcome, verification, rollback, …) moves.
    The artifact's ``generated_at``/tool version stay OUTSIDE the seal."""
    records = [_hashable_record(r) for r in _records_of(artifact_or_records)]
    digest = hashlib.sha256(_canonical_json(records).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _coverage_of(rec: dict) -> str:
    """The recorded coverage level of a record's verification, or ``none``."""
    strength = (rec.get("verification") or {}).get("strength") or {}
    level = strength.get("level")
    return level if level in _COVERAGE_LEVELS else "none"


def proof_manifest(artifact_or_records: Any) -> dict:
    """A compact, human-auditable manifest derived ONLY from the records.

    Counts by outcome and by coverage level, the honest auto-fixed-vs-flagged
    tally, and a one-line verdict — so the summary can never contradict the
    evidence it summarizes."""
    records = _records_of(artifact_or_records)
    by_outcome = {"applied": 0, "rolled_back": 0, "blocked": 0,
                  "skipped_learned": 0}
    by_coverage = {level: 0 for level in _COVERAGE_LEVELS}
    for rec in records:
        outcome = rec.get("outcome", "")
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if outcome == "applied":
            by_coverage[_coverage_of(rec)] += 1

    total = len(records)
    auto_fixed = by_outcome["applied"]
    # "flagged" = everything that did NOT land as an applied fix: a human still
    # owns it (rolled back, blocked, or declined).
    flagged = total - auto_fixed
    return {
        "records": total,
        "by_outcome": by_outcome,
        "by_coverage": by_coverage,
        "auto_fixed": auto_fixed,
        "flagged": flagged,
        "verdict": _verdict(auto_fixed, flagged, by_outcome["rolled_back"]),
    }


def _verdict(auto_fixed: int, flagged: int, rolled_back: int) -> str:
    """One honest line a buyer can read at a glance."""
    if auto_fixed == 0 and flagged == 0:
        return "no fixes recorded"
    if auto_fixed == 0:
        return f"0 auto-fixed, {flagged} flagged for review"
    tail = f", {flagged} flagged for review" if flagged else ""
    rb = f" ({rolled_back} rolled back)" if rolled_back else ""
    return f"{auto_fixed} auto-fixed & recorded{tail}{rb}"


def proof_bundle(artifact_or_records: Any) -> dict:
    """The buyer/CI-facing proof bundle: a stable tamper-evident hash plus an
    auditable manifest, both pure functions of the existing records.

    Accepts a full proof artifact or a bare list of fix records. Deterministic:
    same records in → identical bundle out. No time, no randomness, no
    hash-order dependence."""
    return {
        "schema": BUNDLE_SCHEMA,
        "schema_version": BUNDLE_VERSION,
        "proof_hash": proof_hash(artifact_or_records),
        "summary": proof_manifest(artifact_or_records),
    }
