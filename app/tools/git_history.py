"""Tiny, dependency-free git-history helpers.

Kept deliberately neutral — it imports nothing from ``app`` — so both the
profiler and the exposure engine can use it without forming an import cycle
(found by Apex's own grade after the exposure work landed). Non-git targets
yield ``None``; the result is anchored to the HEAD commit time so it stays
deterministic for a given repo state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def blame_age_days(project_root: str | Path, rel: str, line: int) -> int | None:
    """Days since the commit that last touched ``rel:line``, vs HEAD's time."""
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=project_root,
                              capture_output=True, text=True, timeout=15)

    try:
        head = _git("log", "-1", "--format=%ct")
        if head.returncode != 0 or not head.stdout.strip():
            return None
        blame = _git("blame", "-L", f"{line},{line}", "--porcelain", "--", rel)
        if blame.returncode != 0:
            return None
        for text_line in blame.stdout.splitlines():
            if text_line.startswith("committer-time "):
                then = int(text_line.split()[1])
                return max(0, (int(head.stdout.strip()) - then) // 86400)
    except Exception:
        return None
    return None
