"""Proof-of-VALUE: the measured before->after metric win on a fix record.

``_fix_record`` (via ``build_proof``) attaches an ``impact`` field only when the
apply path observed a metric move, so a no-op fix's record stays byte-identical.
The existing edge suite covers shield_test / verification_strength / converged
extras but not this additive ``impact`` branch — this file pins both directions.

Deterministic and hermetic: dict-built apply summaries, no tmp_path, no clock.
Style mirrors test_proof_of_fix_more_edges.py.
"""

from __future__ import annotations

from app.engine.proof_of_fix import build_proof


def test_fix_record_includes_impact_when_metric_moved():
    # A result row carrying a measured before->after win records it verbatim.
    summary = {
        "results": [
            {"branch": "1", "applied": True, "target": "app/x.py",
             "impact": "max nesting 3->1, cognitive 6->3"},
        ],
    }
    rec = build_proof(summary, "/tmp/p")["fixes"][0]
    assert rec["outcome"] == "applied"
    assert rec["impact"] == "max nesting 3->1, cognitive 6->3"


def test_fix_record_omits_impact_when_no_metric_moved():
    # No metric move -> the field is absent, keeping a no-op fix's record clean.
    summary = {"results": [{"branch": "1", "applied": True, "target": "app/x.py"}]}
    rec = build_proof(summary, "/tmp/p")["fixes"][0]
    assert "impact" not in rec


def test_fix_record_omits_impact_when_falsy():
    # An empty-string impact is falsy and must NOT be recorded (the `if r.get`
    # guard), so a record with no real win stays byte-identical to one with the
    # key entirely absent.
    summary = {"results": [{"branch": "1", "applied": True, "target": "app/x.py",
                            "impact": ""}]}
    rec = build_proof(summary, "/tmp/p")["fixes"][0]
    assert "impact" not in rec
