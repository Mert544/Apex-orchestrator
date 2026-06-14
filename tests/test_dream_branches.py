"""Remaining branch edge for the dream's proof-of-fix review.

Targets 140->139: a block reason that appears only once does NOT clear the
``n >= 2`` repetition bar, so it is silently skipped (only repeated reasons
become patterns).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.dream import DreamReport, _review_proof


def test_review_proof_single_block_reason_not_reported(tmp_path):
    apex = Path(tmp_path) / ".apex"
    apex.mkdir()
    # One fix blocked for a unique reason (count 1) — below the >= 2 bar, so it
    # must not surface as a pattern. A failing test still surfaces (no minimum).
    (apex / "proof-of-fix.json").write_text(json.dumps({"fixes": [
        {"outcome": "blocked",
         "blocked_reason": "lonely reason — only happened once"},
        {"outcome": "rolled_back",
         "verification": {"failing_tests": ["tests/test_x.py::test_a"]}},
    ]}), encoding="utf-8")

    report = DreamReport()
    _review_proof(Path(tmp_path), report)

    joined = "\n".join(report.patterns)
    # The single-occurrence block reason is filtered out by the >= 2 guard...
    assert "lonely reason" not in joined
    # ...while the failing-test pattern (no repetition minimum) is reported.
    assert "tests/test_x.py::test_a" in joined


def test_review_proof_repeated_block_reason_is_reported(tmp_path):
    apex = Path(tmp_path) / ".apex"
    apex.mkdir()
    # The same reason twice crosses the >= 2 bar and becomes a pattern.
    (apex / "proof-of-fix.json").write_text(json.dumps({"fixes": [
        {"outcome": "blocked", "blocked_reason": "needs a covering test"},
        {"outcome": "blocked", "blocked_reason": "needs a covering test"},
    ]}), encoding="utf-8")

    report = DreamReport()
    _review_proof(Path(tmp_path), report)

    joined = "\n".join(report.patterns)
    assert "2 steps blocked for the same reason" in joined
    assert "needs a covering test" in joined
