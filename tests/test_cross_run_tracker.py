from __future__ import annotations

from pathlib import Path

from app.memory.cross_run_tracker import CrossRunTracker, ClaimStatus


def test_tracker_records_new_claims(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        run_id="run-1",
        claims=[
            {"claim": "auth module untested", "branch": "x.a", "confidence": 0.8},
            {"claim": "payment gateway missing guard", "branch": "x.b", "confidence": 0.9},
        ],
    )

    state = tracker.load_state()
    assert len(state["claim_tracker"]) == 2
    assert state["claim_tracker"][0]["status"] == ClaimStatus.OPEN.value
    assert state["claim_tracker"][0]["first_seen_run"] == "run-1"


def test_tracker_updates_existing_claims(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        run_id="run-1",
        claims=[{"claim": "auth module untested", "branch": "x.a", "confidence": 0.8}],
    )
    tracker.record_run_claims(
        run_id="run-2",
        claims=[{"claim": "auth module untested", "branch": "x.a", "confidence": 0.8}],
    )

    state = tracker.load_state()
    claim = state["claim_tracker"][0]
    assert claim["status"] == ClaimStatus.STILL_OPEN.value
    assert claim["first_seen_run"] == "run-1"
    assert claim["last_seen_run"] == "run-2"
    assert claim["run_count"] == 2


def test_tracker_marks_resolved_claims(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        run_id="run-1",
        claims=[{"claim": "auth module untested", "branch": "x.a", "confidence": 0.8}],
    )
    tracker.record_run_claims(
        run_id="run-2",
        claims=[],  # claim no longer present
    )

    state = tracker.load_state()
    assert len(state["claim_tracker"]) == 1
    assert state["claim_tracker"][0]["status"] == ClaimStatus.POTENTIALLY_RESOLVED.value


def test_recall_returns_open_claims(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        run_id="run-1",
        claims=[
            {"claim": "auth module untested", "branch": "x.a", "confidence": 0.8},
            {"claim": "old issue fixed", "branch": "x.z", "confidence": 0.3},
        ],
    )
    # Mark second as resolved manually
    tracker.update_claim_status("old issue fixed", ClaimStatus.RESOLVED)

    open_claims = tracker.get_open_claims()
    assert len(open_claims) == 1
    assert open_claims[0]["claim"] == "auth module untested"


def test_tracker_produces_recall_prompt(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        run_id="run-1",
        claims=[{"claim": "auth module untested", "branch": "x.a", "confidence": 0.8}],
    )

    prompt = tracker.build_recall_prompt()
    assert "Previously identified issues" in prompt
    assert "auth module untested" in prompt
    assert "still present" in prompt.lower()


def test_tracker_limits_claim_history(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    for i in range(55):
        tracker.record_run_claims(
            run_id=f"run-{i}",
            claims=[{"claim": f"issue-{i}", "branch": f"x.{i}", "confidence": 0.5}],
        )

    state = tracker.load_state()
    assert len(state["claim_tracker"]) == 50  # capped


def test_claim_status_enum_values():
    assert ClaimStatus.OPEN.value == "open"
    assert ClaimStatus.STILL_OPEN.value == "still_open"
    assert ClaimStatus.POTENTIALLY_RESOLVED.value == "potentially_resolved"
    assert ClaimStatus.RESOLVED.value == "resolved"
    assert ClaimStatus.WORSENED.value == "worsened"
