"""Characterization test proving _generate_counterexamples is byte-identical
after decomposition into pure helpers. The original implementation is inlined
here as an oracle and compared against the refactored engine over many inputs
that exercise every branch (each keyword, multiple matches, truncation, and the
no-match fallback)."""
from __future__ import annotations

import itertools

from app.engine.recursive_reflection import RecursiveReflectionEngine


def _oracle(text: str, evidence: list[str]) -> list[str]:
    counters = []
    lower = text.lower()

    if "secure" in lower or "safe" in lower:
        counters.append("What if an attacker provides crafted input that bypasses the validation?")
    if "all" in lower or "every" in lower:
        counters.append("What if there is an edge case file or function not covered by the evidence?")
    if "test" in lower or "coverage" in lower:
        counters.append("What if the tests exist but do not actually assert meaningful behavior?")
    if "fast" in lower or "performance" in lower:
        counters.append("What if the performance is acceptable for small inputs but degrades at scale?")
    if "no " in lower or "never" in lower:
        counters.append("What if the issue exists in a dependency or transitive module not scanned?")
    if "thread" in lower or "concurrent" in lower:
        counters.append("What if a race condition occurs under high load that is not visible in static analysis?")
    if not counters:
        counters.append("What if the evidence is outdated and the code has changed since?")
        counters.append("What if the claim holds in the current context but fails in a different environment?")

    return counters[:3]


# Every trigger keyword (incl. exact substrings like "no ") plus non-trigger words.
_TOKENS = [
    "",
    "secure",
    "safe",
    "SAFE",
    "all",
    "every",
    "test",
    "coverage",
    "fast",
    "performance",
    "no ",
    "never",
    "thread",
    "concurrent",
    "CONCURRENT",
    "nothing",
    "wall",
    "everywhere",
    "latest",
    "the code is fine",
]


def _inputs() -> list[str]:
    cases: list[str] = []
    # Singles and the empty string.
    cases.extend(_TOKENS)
    # Pairs and triples to force ordering + truncation to 3.
    for combo in itertools.combinations(_TOKENS, 2):
        cases.append(" ".join(combo))
    for combo in itertools.combinations(_TOKENS, 3):
        cases.append(" ".join(combo))
    # A claim hitting 4+ rules to prove truncation drops later matches.
    cases.append("secure all test fast no  thread")
    cases.append("SAFE EVERY Coverage Performance NEVER Concurrent")
    return cases


def test_generate_counterexamples_byte_identical() -> None:
    mismatches = []
    for text in _inputs():
        expected = _oracle(text, [])
        actual = RecursiveReflectionEngine._generate_counterexamples(text, [])
        if expected != actual:
            mismatches.append((text, expected, actual))
    assert not mismatches, mismatches


def test_full_reflect_byte_identical_counter_examples() -> None:
    engine = RecursiveReflectionEngine()
    for text in _inputs():
        result = engine.reflect({"text": text, "evidence": [], "confidence": 0.6})
        assert result.counter_examples == _oracle(text, [])
