"""Proof-of-Fix: tool-version fallback, error counts, and shield-test records."""

from __future__ import annotations

from types import SimpleNamespace

import app.engine.proof_of_fix as pof
from app.engine.proof_of_fix import build_proof, summarize_test_run, tool_version


def test_tool_version_returns_unknown_when_lookup_raises(monkeypatch):
    # The except branch: importlib.metadata.version may raise for an
    # uninstalled package -> best-effort "unknown".
    import importlib.metadata as md

    def boom(_name):
        raise md.PackageNotFoundError("apex-orchestrator")

    monkeypatch.setattr(md, "version", boom)
    assert tool_version() == "unknown"


def test_tool_version_is_a_string():
    # Whatever the environment reports, it is a plain string (never raises).
    assert isinstance(tool_version(), str)


def test_summarize_counts_errors_from_output():
    # The errors-bump branch: "N error(s)" is totalled into the errors field.
    summary = SimpleNamespace(
        commands=[["pytest"]],
        ok=False,
        results=[{"stdout": "2 errors in 0.50s", "stderr": "",
                  "duration_seconds": 0.5}],
    )
    ev = summarize_test_run(summary)
    assert ev["errors"] == 2
    assert ev["tests_passed"] == 0
    assert ev["tests_failed"] == 0


def test_summarize_totals_duration_across_results():
    summary = SimpleNamespace(
        commands=[["pytest"]],
        ok=True,
        results=[
            {"stdout": "1 passed in 0.10s", "stderr": "", "duration_seconds": 0.1},
            {"stdout": "2 passed in 0.20s", "stderr": "", "duration_seconds": 0.2},
        ],
    )
    ev = summarize_test_run(summary)
    assert ev["tests_passed"] == 3
    assert ev["duration_seconds"] == 0.3


def test_fix_record_includes_shield_test_when_present():
    summary = {
        "results": [
            {"branch": "1", "applied": True, "target": "app/x.py",
             "shield_test": "tests/test_shield_x.py",
             "test_evidence": {"performed": True}},
        ],
    }
    proof = build_proof(summary, "/tmp/p")
    rec = proof["fixes"][0]
    assert rec["outcome"] == "applied"
    assert rec["shield_test"] == "tests/test_shield_x.py"


def test_fix_record_omits_shield_test_when_absent():
    summary = {"results": [{"branch": "1", "applied": True, "target": "app/x.py"}]}
    rec = build_proof(summary, "/tmp/p")["fixes"][0]
    assert "shield_test" not in rec


def test_verification_strength_is_recorded_on_record():
    summary = {
        "results": [
            {"branch": "1", "applied": True, "target": "app/x.py",
             "test_evidence": {"performed": True},
             "verification_strength": {"level": "none"}},
        ],
    }
    rec = build_proof(summary, "/tmp/p")["fixes"][0]
    assert rec["verification"]["strength"] == {"level": "none"}


def test_module_schema_constants_present():
    assert pof.SCHEMA and pof.SCHEMA_VERSION
