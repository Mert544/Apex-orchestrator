from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FeedbackEntry:
    """A single feedback event."""

    node_key: str  # "issue:file:line" format
    old_confidence: float
    feedback_score: float  # +1.0 success, -0.5 failure
    new_confidence: float
    timestamp: str
    action_type: str
    run_id: str = ""  # Unique run identifier for deduplication
    source: str = "auto"  # "auto" or "human"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "old_confidence": self.old_confidence,
            "feedback_score": self.feedback_score,
            "new_confidence": self.new_confidence,
            "timestamp": self.timestamp,
            "action_type": self.action_type,
            "run_id": self.run_id,
            "source": self.source,
        }


class FeedbackLoop:
    """Closed-loop feedback: action results update fractal node confidence.

    Features:
    - Exponential Moving Average (EMA) with configurable alpha
    - Deduplication: prevents duplicate feedback for same node within time window
    - Confidence decay: older entries have less weight over time
    - Memory hygiene: cleanup old/irrelevant entries

    Usage:
        loop = FeedbackLoop()
        new_conf = loop.update("eval:auth.py:5", old_conf=0.9, score=1.0)
    """

    def __init__(
        self,
        alpha: float = 0.3,
        log_dir: str = ".apex",
        dedup_window_seconds: int = 300,
        decay_halflife_days: int = 30,
        max_entries_per_node: int = 50,
    ) -> None:
        self.alpha = alpha
        self.log_path = Path(log_dir) / "feedback_log.json"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[FeedbackEntry] = []
        self.dedup_window_seconds = dedup_window_seconds
        self.decay_halflife_days = decay_halflife_days
        self.max_entries_per_node = max_entries_per_node
        self._load()

    def _load(self) -> None:
        if self.log_path.exists():
            try:
                data = json.loads(self.log_path.read_text(encoding="utf-8"))
                self.entries = [FeedbackEntry(**e) for e in data.get("entries", [])]
            except Exception:
                self.entries = []

    def _save(self) -> None:
        self.log_path.write_text(
            json.dumps(
                {"entries": [e.to_dict() for e in self.entries], "version": "2.0"},
                indent=2,
            ),
            encoding="utf-8",
        )

    def _is_duplicate(self, node_key: str, run_id: str, action_type: str) -> bool:
        """Check if this is a duplicate feedback within the dedup window."""
        if not run_id:
            return False

        current_time = time.time()
        for entry in reversed(self.entries[-10:]):
            if entry.node_key == node_key and entry.run_id == run_id:
                if entry.action_type == action_type:
                    return True
        return False

    def _apply_decay(self, entry: FeedbackEntry) -> float:
        """Apply time-based decay to older entries."""
        try:
            entry_time = time.mktime(
                time.strptime(entry.timestamp, "%Y-%m-%d %H:%M:%S")
            )
            current_time = time.time()
            days_old = (current_time - entry_time) / 86400

            halflife = self.decay_halflife_days
            decay_factor = 0.5 ** (days_old / halflife)
            return decay_factor
        except Exception:
            return 1.0

    def _cleanup_memory(self) -> int:
        """Remove old/low-value entries to prevent memory pollution."""
        if len(self.entries) <= self.max_entries_per_node * 10:
            return 0

        removed = 0
        by_node: dict[str, list[tuple[int, FeedbackEntry]]] = defaultdict(list)
        for i, e in enumerate(self.entries):
            by_node[e.node_key].append((i, e))

        for node_key, node_entries in by_node.items():
            if len(node_entries) > self.max_entries_per_node:
                entries_to_remove = node_entries[: -self.max_entries_per_node]
                indices_to_remove = {i for i, _ in entries_to_remove}

                self.entries = [
                    e for i, e in enumerate(self.entries) if i not in indices_to_remove
                ]
                removed += len(indices_to_remove)

        return removed

    def update(
        self,
        node_key: str,
        old_confidence: float,
        feedback_score: float,
        action_type: str = "",
        run_id: str = "",
        source: str = "auto",
    ) -> float | None:
        """Update confidence with EMA and deduplication. Returns new confidence or None if duplicate."""
        if self._is_duplicate(node_key, run_id, action_type):
            return None

        new_confidence = old_confidence * (1 - self.alpha) + feedback_score * self.alpha
        new_confidence = max(0.0, min(1.0, new_confidence))

        entry = FeedbackEntry(
            node_key=node_key,
            old_confidence=old_confidence,
            feedback_score=feedback_score,
            new_confidence=new_confidence,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            action_type=action_type,
            run_id=run_id,
            source=source,
        )
        self.entries.append(entry)
        self._cleanup_memory()
        self._save()
        return new_confidence

    def get_history(
        self, node_key: str, include_decayed: bool = False
    ) -> list[FeedbackEntry]:
        """Get feedback history for a specific node."""
        history = [e for e in self.entries if e.node_key == node_key]
        if not include_decayed:
            return history
        return history

    def get_weighted_feedback(self, node_key: str) -> float:
        """Get time-decayed weighted average feedback for a node."""
        history = self.get_history(node_key)
        if not history:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for entry in history:
            weight = self._apply_decay(entry)
            weighted_sum += entry.feedback_score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return weighted_sum / total_weight

    def get_average_feedback(self, node_key: str) -> float:
        """Get average feedback score for a node (legacy method)."""
        return self.get_weighted_feedback(node_key)

    def get_node_confidence(self, node_key: str) -> float:
        """Get current confidence for a node based on weighted history."""
        return self.get_weighted_feedback(node_key)

    def should_skip(self, node_key: str, threshold: float = -0.2) -> bool:
        """Return True if this node consistently gets negative feedback."""
        avg = self.get_weighted_feedback(node_key)
        return avg < threshold

    def get_statistics(self) -> dict[str, Any]:
        """Get memory statistics for monitoring."""
        by_node: dict[str, int] = defaultdict(int)
        by_action: dict[str, int] = defaultdict(int)
        by_source: dict[str, int] = defaultdict(int)

        for e in self.entries:
            by_node[e.node_key] += 1
            by_action[e.action_type] += 1
            by_source[e.source] += 1

        return {
            "total_entries": len(self.entries),
            "unique_nodes": len(by_node),
            "entries_by_action": dict(by_action),
            "entries_by_source": dict(by_source),
            "top_nodes": sorted(by_node.items(), key=lambda x: -x[1])[:10],
        }

    def clear_duplicates(self) -> int:
        """Remove duplicate entries, keeping only the latest for each node/action pair."""
        seen = set()
        original_len = len(self.entries)
        self.entries = [
            e
            for e in self.entries
            if (e.node_key, e.action_type) not in seen
            and not seen.add((e.node_key, e.action_type))
        ]
        removed = original_len - len(self.entries)
        if removed > 0:
            self._save()
        return removed
