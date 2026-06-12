"""SecurityGovernor: blocked claim patterns score 0.0 — real behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.skills.security_governor import SecurityGovernor


@pytest.mark.parametrize("pattern", sorted(SecurityGovernor.BLOCKED_PATTERNS))
def test_every_blocked_pattern_zeroes_the_score(pattern):
    node = SimpleNamespace(claim=f"plan includes {pattern.upper()} somewhere")
    assert SecurityGovernor().review(node) == 0.0  # case-insensitive match


def test_clean_claim_passes_with_high_confidence():
    node = SimpleNamespace(claim="refactor the parser into two modules")
    assert SecurityGovernor().review(node) == 0.95
