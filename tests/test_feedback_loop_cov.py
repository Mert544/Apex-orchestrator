from __future__ import annotations

import json
from pathlib import Path

from app.engine.feedback_loop import FeedbackEntry, FeedbackLoop


def test_load_corrupt_log_resets_entries(tmp_path: Path):
    # A malformed feedback_log.json must not crash construction: the except
    # branch (lines 74-75) swallows the error and starts empty.
    log = tmp_path / "feedback_log.json"
    log.write_text("{ not valid json", encoding="utf-8")
    loop = FeedbackLoop(log_dir=str(tmp_path))
    assert loop.entries == []


def test_load_existing_entries(tmp_path: Path):
    # Round-trip: a saved log re-loads its entries on next construction.
    first = FeedbackLoop(log_dir=str(tmp_path))
    first.update("eval:x.py:1", old_confidence=0.5, feedback_score=1.0)
    second = FeedbackLoop(log_dir=str(tmp_path))
    assert len(second.entries) == 1
    assert second.entries[0].node_key == "eval:x.py:1"


def test_apply_decay_bad_timestamp_returns_one(tmp_path: Path):
    # A non-parseable timestamp drives _apply_decay into its except branch
    # (lines 109-110), which returns a neutral weight of 1.0.
    loop = FeedbackLoop(log_dir=str(tmp_path))
    entry = FeedbackEntry(
        node_key="n",
        old_confidence=0.5,
        feedback_score=1.0,
        new_confidence=0.6,
        timestamp="not-a-timestamp",
        action_type="eval",
    )
    assert loop._apply_decay(entry) == 1.0


def test_weighted_feedback_uses_neutral_weight_on_bad_timestamp(tmp_path: Path):
    # With a single entry whose decay falls back to 1.0, the weighted average
    # equals its raw score.
    loop = FeedbackLoop(log_dir=str(tmp_path))
    loop.entries.append(
        FeedbackEntry(
            node_key="n",
            old_confidence=0.5,
            feedback_score=-0.5,
            new_confidence=0.4,
            timestamp="bogus",
            action_type="eval",
        )
    )
    assert loop.get_weighted_feedback("n") == -0.5


def test_weighted_feedback_zero_total_weight_returns_zero(tmp_path: Path, monkeypatch):
    # Force every decay weight to 0.0 so total_weight == 0 (line 188-189),
    # exercising the guarded division-by-zero return.
    loop = FeedbackLoop(log_dir=str(tmp_path))
    loop.entries.append(
        FeedbackEntry(
            node_key="n",
            old_confidence=0.5,
            feedback_score=1.0,
            new_confidence=0.6,
            timestamp="2020-01-01 00:00:00",
            action_type="eval",
        )
    )
    monkeypatch.setattr(loop, "_apply_decay", lambda _e: 0.0)
    assert loop.get_weighted_feedback("n") == 0.0


def test_get_history_include_decayed_returns_history(tmp_path: Path):
    # include_decayed=True hits the second return path (line 172); current
    # behavior returns the same history list.
    loop = FeedbackLoop(log_dir=str(tmp_path))
    loop.update("n", old_confidence=0.5, feedback_score=1.0)
    plain = loop.get_history("n")
    decayed = loop.get_history("n", include_decayed=True)
    assert [e.node_key for e in decayed] == [e.node_key for e in plain]
    assert len(decayed) == 1


def test_cleanup_memory_trims_excess_entries(tmp_path: Path):
    # _cleanup_memory only fires once total entries exceed max_per_node * 10
    # (line 114 guard), then trims each node down to max_per_node (lines 117-132).
    loop = FeedbackLoop(log_dir=str(tmp_path), max_entries_per_node=2)
    # Threshold is 2 * 10 = 20 total entries; add 25 for a single node.
    for i in range(25):
        loop.entries.append(
            FeedbackEntry(
                node_key="node",
                old_confidence=0.5,
                feedback_score=1.0,
                new_confidence=0.6,
                timestamp="2020-01-01 00:00:00",
                action_type="eval",
                run_id=str(i),
            )
        )
    removed = loop._cleanup_memory()
    assert removed == 23
    assert len(loop.entries) == 2
    # The kept entries are the most recent ones.
    assert [e.run_id for e in loop.entries] == ["23", "24"]


def test_cleanup_memory_noop_below_threshold(tmp_path: Path):
    # Below the threshold the early return (line 114-115) yields 0 removed.
    loop = FeedbackLoop(log_dir=str(tmp_path), max_entries_per_node=2)
    loop.entries.append(
        FeedbackEntry(
            node_key="node",
            old_confidence=0.5,
            feedback_score=1.0,
            new_confidence=0.6,
            timestamp="2020-01-01 00:00:00",
            action_type="eval",
        )
    )
    assert loop._cleanup_memory() == 0


def test_save_writes_versioned_payload(tmp_path: Path):
    loop = FeedbackLoop(log_dir=str(tmp_path))
    loop.update("n", old_confidence=0.5, feedback_score=1.0)
    data = json.loads((tmp_path / "feedback_log.json").read_text(encoding="utf-8"))
    assert data["version"] == "2.0"
    assert data["entries"][0]["node_key"] == "n"
