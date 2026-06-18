"""Tests for app/engine/self_assessment.py — Apex grading its OWN fixing.

These build proof histories shaped like ``proof_history.load_proof_history``
output (a list of ``{"schema", "fixes": [...]}`` dicts) and assert that
weaknesses rank low-reliability/high-attempt first, the curriculum names the
right directions, calibration measures over/under-confidence, results are
deterministic and bounded, and empty history is empty/neutral and never raises.
"""

from __future__ import annotations

from app.engine.proof_of_fix import SCHEMA
from app.engine.self_assessment import (
    assess_weaknesses,
    confidence_calibration,
    self_curriculum,
)


def _fix(action: str, outcome: str, *, performed: bool = True) -> dict:
    """A minimal proof fix record: an action, a terminal outcome, and whether
    Apex claimed a performed verification (its stated confidence)."""
    return {
        "finding": {"action": action},
        "outcome": outcome,
        "verification": {"performed": performed},
    }


def _proof(*fixes: dict) -> dict:
    return {"schema": SCHEMA, "fixes": list(fixes)}


def _history(*fixes: dict) -> list[dict]:
    return [_proof(*fixes)]


# --- weakness ranking ------------------------------------------------------

def test_weaknesses_rank_low_reliability_high_attempt_first():
    # strong: 3 applied (reliability 1.0)
    # rolly:  1 applied, 3 rolled_back (reliability 0.25)
    # blocky: 1 applied, 3 blocked     (reliability 0.25, fewer ... same lost)
    history = _history(
        _fix("strong", "applied"),
        _fix("strong", "applied"),
        _fix("strong", "applied"),
        _fix("rolly", "applied"),
        _fix("rolly", "rolled_back"),
        _fix("rolly", "rolled_back"),
        _fix("rolly", "rolled_back"),
        _fix("blocky", "applied"),
        _fix("blocky", "blocked"),
        _fix("blocky", "blocked"),
    )
    weak = assess_weaknesses(history)
    actions = [w["action"] for w in weak]
    # The two 0.25 actions outrank the reliable one; the one with more lost
    # (rolly: 3 lost) outranks blocky (2 lost). strong is reliable but kept.
    assert actions == ["rolly", "blocky", "strong"]
    assert weak[0]["reliability"] == 0.25
    assert weak[0]["attempts"] == 4
    assert weak[0]["lost"] == 3
    assert weak[0]["verdict"] == "fragile — rolls back often"


def test_blocked_verdict_when_blocks_dominate_losses():
    history = _history(
        _fix("gated", "applied"),
        _fix("gated", "blocked"),
        _fix("gated", "blocked"),
        _fix("gated", "blocked"),
    )
    weak = assess_weaknesses(history)
    assert weak[0]["verdict"] == "blocked — preconditions usually unmet"


def test_reliable_action_above_threshold():
    history = _history(
        _fix("solid", "applied"),
        _fix("solid", "applied"),
        _fix("solid", "rolled_back"),
    )
    weak = assess_weaknesses(history)
    # reliability 0.6667 >= 0.5 -> reliable verdict
    assert weak[0]["verdict"] == "reliable"


def test_low_attempt_actions_excluded_as_noise():
    # 'oneoff' rolled back once (1 attempt) is below the min-attempts floor.
    history = _history(
        _fix("oneoff", "rolled_back"),
        _fix("steady", "applied"),
        _fix("steady", "applied"),
    )
    actions = [w["action"] for w in assess_weaknesses(history)]
    assert "oneoff" not in actions
    assert "steady" in actions


def test_unknown_action_bucket_excluded():
    history = _history(
        {"outcome": "rolled_back", "verification": {"performed": True}},
        {"outcome": "rolled_back", "verification": {"performed": True}},
    )
    assert assess_weaknesses(history) == []


def test_weaknesses_bounded():
    fixes = []
    for i in range(40):
        name = f"act{i:02d}"
        fixes.extend([_fix(name, "applied"), _fix(name, "rolled_back")])
    weak = assess_weaknesses(_history(*fixes))
    assert len(weak) <= 12
    for w in weak:
        assert 0.0 <= w["reliability"] <= 1.0
        assert w["lost"] >= 0 and w["attempts"] >= w["lost"]


# --- curriculum ------------------------------------------------------------

def test_curriculum_picks_top_directions():
    history = _history(
        _fix("rolly", "applied"),
        _fix("rolly", "rolled_back"),
        _fix("rolly", "rolled_back"),
        _fix("gated", "applied"),
        _fix("gated", "blocked"),
        _fix("gated", "blocked"),
    )
    lines = self_curriculum(history, top=2)
    assert len(lines) == 2
    assert any("rolly" in line and "without rollback" in line for line in lines)
    assert any("gated" in line and "preconditions" in line for line in lines)


def test_curriculum_respects_top_and_zero():
    history = _history(
        _fix("a", "rolled_back"),
        _fix("a", "rolled_back"),
        _fix("b", "rolled_back"),
        _fix("b", "rolled_back"),
    )
    assert len(self_curriculum(history, top=1)) == 1
    assert self_curriculum(history, top=0) == []
    assert self_curriculum(history, top=-5) == []


def test_curriculum_clamps_to_available():
    history = _history(_fix("a", "rolled_back"), _fix("a", "rolled_back"))
    assert len(self_curriculum(history, top=10)) == 1


# --- calibration -----------------------------------------------------------

def test_calibration_overconfident():
    # claims verification on every fix (claimed 1.0) but only half land.
    history = _history(
        _fix("x", "applied", performed=True),
        _fix("x", "applied", performed=True),
        _fix("x", "rolled_back", performed=True),
        _fix("x", "rolled_back", performed=True),
    )
    cal = confidence_calibration(history)
    assert cal["claimed"] == 1.0
    assert cal["actual"] == 0.5
    assert cal["gap"] == 0.5
    assert cal["verdict"] == "over-confident — claims more than lands"
    assert cal["fixes"] == 4


def test_calibration_underconfident():
    # all land (actual 1.0) but Apex only claimed verification on one (0.25).
    history = _history(
        _fix("x", "applied", performed=True),
        _fix("x", "applied", performed=False),
        _fix("x", "applied", performed=False),
        _fix("x", "applied", performed=False),
    )
    cal = confidence_calibration(history)
    assert cal["claimed"] == 0.25
    assert cal["actual"] == 1.0
    assert cal["gap"] == -0.75
    assert cal["verdict"] == "under-confident — lands more than it claims"


def test_calibration_well_calibrated():
    history = _history(
        _fix("x", "applied", performed=True),
        _fix("x", "rolled_back", performed=False),
    )
    cal = confidence_calibration(history)
    # claimed 0.5, actual 0.5 -> gap 0.0
    assert cal["gap"] == 0.0
    assert cal["verdict"] == "well calibrated"


def test_calibration_bounded():
    history = _history(
        _fix("x", "applied", performed=True),
        _fix("y", "blocked", performed=False),
        _fix("z", "rolled_back", performed=True),
    )
    cal = confidence_calibration(history)
    assert 0.0 <= cal["claimed"] <= 1.0
    assert 0.0 <= cal["actual"] <= 1.0
    assert -1.0 <= cal["gap"] <= 1.0


# --- determinism + empty ---------------------------------------------------

def test_deterministic():
    history = _history(
        _fix("rolly", "rolled_back"),
        _fix("rolly", "applied"),
        _fix("gated", "blocked"),
        _fix("gated", "blocked"),
    )
    assert assess_weaknesses(history) == assess_weaknesses(history)
    assert self_curriculum(history) == self_curriculum(history)
    assert confidence_calibration(history) == confidence_calibration(history)


def test_empty_history_is_empty_and_neutral():
    assert assess_weaknesses([]) == []
    assert self_curriculum([]) == []
    cal = confidence_calibration([])
    assert cal == {
        "claimed": 0.0,
        "actual": 0.0,
        "gap": 0.0,
        "verdict": "no evidence",
        "fixes": 0,
    }


def test_none_and_malformed_tolerated():
    assert assess_weaknesses(None) == []  # type: ignore[arg-type]
    assert self_curriculum(None) == []  # type: ignore[arg-type]
    assert confidence_calibration(None)["verdict"] == "no evidence"  # type: ignore[arg-type]
    junk = [{"schema": SCHEMA, "fixes": [None, 7, {"outcome": "applied"}]}]
    assert confidence_calibration(junk)["fixes"] == 1
