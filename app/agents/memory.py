from __future__ import annotations

"""AgentMemory — persistent voting history and pattern learning for agents.

Agents remember past evaluations and use them to:
1. Fast-path similar claims (cache hits)
2. Adjust confidence based on historical accuracy
3. Learn which claim patterns each agent is good at evaluating
"""

import hashlib
import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.consensus import Vote


@dataclass
class MemoryEntry:
    claim_hash: str
    claim_preview: str
    votes: list[Vote]
    final_verdict: str
    timestamp: float
    hit_count: int = 1


class AgentMemory:
    """Memory store for agent consensus decisions.

    Stores claim_hash → votes mappings and enables:
    - Exact match retrieval
    - Similar claim matching (simple substring similarity)
    - Confidence calibration over time
    """

    def __init__(self, memory_dir: str | Path | None = None) -> None:
        self.memory_dir = Path(memory_dir) if memory_dir else None
        self._entries: dict[str, MemoryEntry] = {}
        self._pattern_confidence: dict[str, dict[str, float]] = {}
        self._load()

    def _hash(self, claim: str) -> str:
        return hashlib.sha256(claim.encode()).hexdigest()[:16]

    def _load(self) -> None:
        if not (self.memory_dir and (self.memory_dir / "agent_memory.json").exists()):
            return
        try:
            with open(self.memory_dir / "agent_memory.json", encoding="utf-8") as f:
                data = json.load(f)
            for entry_data in data.get("entries", []):
                votes = [
                    Vote(
                        agent_name=v["agent_name"],
                        agent_role=v["agent_role"],
                        verdict=getattr(importlib.import_module("app.agents.consensus").Verdict, v["verdict"]),
                        confidence=v["confidence"],
                        reasoning=v["reasoning"],
                        weight=v.get("weight", 1.0),
                    )
                    for v in entry_data["votes"]
                ]
                entry = MemoryEntry(
                    claim_hash=entry_data["claim_hash"],
                    claim_preview=entry_data["claim_preview"],
                    votes=votes,
                    final_verdict=entry_data["final_verdict"],
                    timestamp=entry_data["timestamp"],
                    hit_count=entry_data.get("hit_count", 1),
                )
                self._entries[entry.claim_hash] = entry
            self._pattern_confidence = data.get("pattern_confidence", {})
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    def _save(self) -> None:
        if not self.memory_dir:
            return
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": [
                {
                    "claim_hash": e.claim_hash,
                    "claim_preview": e.claim_preview,
                    "votes": [
                        {
                            "agent_name": v.agent_name,
                            "agent_role": v.agent_role,
                            "verdict": v.verdict.name,
                            "confidence": v.confidence,
                            "reasoning": v.reasoning,
                            "weight": v.weight,
                        }
                        for v in e.votes
                    ],
                    "final_verdict": e.final_verdict,
                    "timestamp": e.timestamp,
                    "hit_count": e.hit_count,
                }
                for e in self._entries.values()
            ],
            "pattern_confidence": self._pattern_confidence,
        }
        with open(self.memory_dir / "agent_memory.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def remember(self, claim: str, votes: list[Vote], final_verdict: str) -> None:
        """Store a consensus decision in memory."""
        h = self._hash(claim)
        if h in self._entries:
            self._entries[h].hit_count += 1
        else:
            self._entries[h] = MemoryEntry(
                claim_hash=h,
                claim_preview=claim[:200],
                votes=votes,
                final_verdict=final_verdict,
                timestamp=time.time(),
            )
        self._update_pattern_confidence(claim, votes)
        self._save()

    def _update_pattern_confidence(self, claim: str, votes: list[Vote]) -> None:
        """Learn which agents are confident on which claim patterns."""
        claim_lower = claim.lower()
        patterns = {
            "security": ["eval", "exec", "os.system", "pickle", "secret", "password", "sql", "inject"],
            "docstring": ["docstring", "document", "comment", "readme"],
            "test": ["test", "coverage", "pytest", "unittest", "verify"],
            "architecture": ["dependency", "coupling", "module", "import", "hub", "boundary", "refactor"],
        }
        for pattern_name, keywords in patterns.items():
            if any(kw in claim_lower for kw in keywords):
                for vote in votes:
                    key = f"{vote.agent_role}:{pattern_name}"
                    old = self._pattern_confidence.get(key, 0.5)
                    # Exponential moving average
                    self._pattern_confidence[key] = old * 0.9 + vote.confidence * 0.1

    def recall(self, claim: str) -> list[Vote] | None:
        """Try to recall votes for an identical or very similar claim."""
        h = self._hash(claim)
        if h in self._entries:
            self._entries[h].hit_count += 1
            return self._entries[h].votes

        # Substring similarity fallback
        claim_lower = claim.lower()
        for entry in self._entries.values():
            preview_lower = entry.claim_preview.lower()
            # If one is substring of the other and length ratio > 0.7
            if (claim_lower in preview_lower or preview_lower in claim_lower):
                min_len = min(len(claim), len(entry.claim_preview))
                max_len = max(len(claim), len(entry.claim_preview))
                if min_len / max_len > 0.7:
                    entry.hit_count += 1
                    return entry.votes
        return None

    def get_learned_confidence(self, agent_role: str, claim: str) -> float | None:
        """Get learned confidence boost for an agent on a claim pattern."""
        claim_lower = claim.lower()
        patterns = {
            "security": ["eval", "exec", "os.system", "pickle", "secret", "password", "sql"],
            "docstring": ["docstring", "document", "comment"],
            "test": ["test", "coverage", "pytest", "verify"],
            "architecture": ["dependency", "coupling", "module", "import", "hub", "boundary"],
        }
        for pattern_name, keywords in patterns.items():
            if any(kw in claim_lower for kw in keywords):
                key = f"{agent_role}:{pattern_name}"
                return self._pattern_confidence.get(key)
        return None

    def stats(self) -> dict[str, Any]:
        return {
            "total_entries": len(self._entries),
            "total_hits": sum(e.hit_count for e in self._entries.values()),
            "pattern_confidence_keys": len(self._pattern_confidence),
        }
