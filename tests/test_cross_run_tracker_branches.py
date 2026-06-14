"""Branch-path coverage for the cross-run claim tracker.

Targets the partial branches left after the existing edge tests:
  - record_run_claims when a re-seen claim is already past OPEN status
    (the OPEN->STILL_OPEN promotion is skipped, 96->98);
  - update_claim_status when no stored claim matches (135->139, no break).
"""

from __future__ import annotations

from pathlib import Path

from app.memory.cross_run_tracker import ClaimStatus, CrossRunTracker


def test_reseen_non_open_claim_keeps_status_but_advances_counters(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    # Seed a tracker entry already promoted past OPEN.
    state = {
        "schema_version": 1,
        "claim_tracker": [
            {
                "claim": "auth untested",
                "branch": "x.a",
                "confidence": 0.8,
                "status": ClaimStatus.POTENTIALLY_RESOLVED.value,
                "first_seen_run": "run-1",
                "last_seen_run": "run-1",
                "run_count": 2,
                "history": [{"run_id": "run-1", "confidence": 0.8}],
            }
        ],
        "runs": [],
    }
    tracker.save_state(state)

    tracker.record_run_claims(
        "run-2", [{"claim": "auth untested", "branch": "x.a", "confidence": 0.9}]
    )

    reloaded = tracker.load_state()
    tc = reloaded["claim_tracker"][0]
    # Status is NOT changed to STILL_OPEN (it was not OPEN), but the claim is
    # re-seen so its last_seen and run_count advance.
    assert tc["status"] == ClaimStatus.POTENTIALLY_RESOLVED.value
    assert tc["last_seen_run"] == "run-2"
    assert tc["run_count"] == 3
    assert tc["history"][-1] == {"run_id": "run-2", "confidence": 0.9}


def test_update_claim_status_no_match_is_a_noop(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        "run-1", [{"claim": "present claim", "confidence": 0.5}]
    )

    # No stored claim matches -> loop falls through without break, state saved.
    tracker.update_claim_status("absent claim", ClaimStatus.RESOLVED)

    claims = tracker.load_state()["claim_tracker"]
    assert len(claims) == 1
    assert claims[0]["claim"] == "present claim"
    # The unrelated claim is untouched.
    assert claims[0]["status"] == ClaimStatus.OPEN.value
