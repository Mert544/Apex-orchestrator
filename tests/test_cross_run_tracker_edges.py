from __future__ import annotations

import json
from pathlib import Path

from app.memory.cross_run_tracker import ClaimStatus, CrossRunTracker, TrackedClaim


def test_load_state_default_when_missing(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    state = tracker.load_state()
    assert state["claim_tracker"] == []
    assert state["runs"] == []


def test_load_state_recovers_from_corrupt_file(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.memory_dir.mkdir(parents=True, exist_ok=True)
    tracker.memory_file.write_text("}{ broken", encoding="utf-8")
    state = tracker.load_state()
    # except branch -> default state.
    assert state["claim_tracker"] == []
    assert state["schema_version"] == 1


def test_load_state_recovers_from_non_dict(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.memory_dir.mkdir(parents=True, exist_ok=True)
    tracker.memory_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    state = tracker.load_state()
    assert isinstance(state, dict)
    assert state["runs"] == []


def test_tracked_claim_roundtrip_to_from_dict():
    tc = TrackedClaim(
        claim="claim x",
        branch="x.a",
        confidence=0.5,
        status=ClaimStatus.OPEN,
        first_seen_run="run-1",
        last_seen_run="run-2",
        run_count=2,
        history=[{"run_id": "run-1"}],
    )
    restored = TrackedClaim.from_dict(tc.to_dict())
    assert restored == tc


def test_from_dict_applies_defaults_for_sparse_data():
    restored = TrackedClaim.from_dict({"claim": "only claim"})
    assert restored.branch == ""
    assert restored.confidence == 0.0
    assert restored.status == ClaimStatus.OPEN
    assert restored.run_count == 1
    assert restored.history == []


def test_claim_marked_potentially_resolved_when_absent(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        "run-1", [{"claim": "leaky abstraction", "branch": "x.a", "confidence": 0.8}]
    )
    # Second run omits the claim -> it should flip to potentially_resolved.
    tracker.record_run_claims(
        "run-2", [{"claim": "different issue", "branch": "x.b", "confidence": 0.6}]
    )
    state = tracker.load_state()
    by_claim = {tc["claim"]: tc for tc in state["claim_tracker"]}
    assert by_claim["leaky abstraction"]["status"] == ClaimStatus.POTENTIALLY_RESOLVED.value
    # The absent record appends a history entry noting the change.
    assert by_claim["leaky abstraction"]["history"][-1]["status_change"] == "absent"


def test_update_claim_status_changes_matching_claim(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        "run-1", [{"claim": "Untested Module", "branch": "x.a", "confidence": 0.8}]
    )
    # Case-insensitive match against the stored claim.
    tracker.update_claim_status("untested module", ClaimStatus.RESOLVED)
    state = tracker.load_state()
    assert state["claim_tracker"][0]["status"] == ClaimStatus.RESOLVED.value


def test_update_claim_status_noop_when_no_match(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        "run-1", [{"claim": "real claim", "branch": "x.a", "confidence": 0.8}]
    )
    tracker.update_claim_status("does not exist", ClaimStatus.WORSENED)
    state = tracker.load_state()
    assert state["claim_tracker"][0]["status"] == ClaimStatus.OPEN.value


def test_build_recall_prompt_empty(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    assert tracker.build_recall_prompt() == "No previously identified open issues on record."


def test_build_recall_prompt_lists_open_claims(tmp_path: Path):
    tracker = CrossRunTracker(tmp_path)
    tracker.record_run_claims(
        "run-1", [{"claim": "missing guard", "branch": "x.a", "confidence": 0.9}]
    )
    prompt = tracker.build_recall_prompt()
    assert "Previously identified issues:" in prompt
    assert "missing guard" in prompt
    assert "branch: x.a" in prompt


def test_find_confidence_returns_zero_when_absent(tmp_path: Path):
    # _find_confidence falls through to 0.0 when no claim matches.
    assert CrossRunTracker._find_confidence([{"claim": "a", "confidence": 0.5}], "zzz") == 0.0
    assert CrossRunTracker._find_confidence([{"claim": "a", "confidence": 0.5}], "a") == 0.5
