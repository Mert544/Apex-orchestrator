"""Characterization proof that the refactored ``_build_swarm_for_plan`` is
byte-identical (in observable behavior) to the original implementation.

The original function body is reconstructed verbatim from the agent classes and
SwarmCoordinator, then both implementations are exercised over a corpus of
plan names that covers every keyword branch and the broad-sweep branch, in both
``use_fractal`` modes. The observable result of the function is the set of
agents registered into the coordinator's registry (keyed by role) plus the
ordered selection of agent classes; both must match exactly.
"""

from __future__ import annotations

import itertools

from app.agents.skills import (
    SecurityAgent,
    DocstringAgent,
    TestStubAgent,
    DependencyAgent,
)
from app.agents.fractal_agents import (
    FractalSecurityAgent,
    FractalDocstringAgent,
    FractalTestStubAgent,
)
from app.agents.swarm_coordinator import SwarmCoordinator
from app.main import _build_swarm_for_plan


def _original_build_swarm_for_plan(
    plan_name: str, use_fractal: bool = False
) -> SwarmCoordinator:
    """Verbatim copy of the pre-refactor implementation (HEAD snapshot)."""
    coord = SwarmCoordinator()

    broad = "project_scan" in plan_name or "full" in plan_name or "self" in plan_name

    agents = []
    if "security" in plan_name or broad:
        agents.append(FractalSecurityAgent() if use_fractal else SecurityAgent())
    if "docstring" in plan_name or "semantic" in plan_name or broad:
        agents.append(FractalDocstringAgent() if use_fractal else DocstringAgent())
    if (
        "test" in plan_name
        or "coverage" in plan_name
        or "semantic" in plan_name
        or broad
    ):
        agents.append(FractalTestStubAgent() if use_fractal else TestStubAgent())
    if "dependency" in plan_name or broad:
        agents.append(DependencyAgent())

    coord.register_agents(agents)
    return coord


def _observable(coord: SwarmCoordinator):
    """Capture the full observable state a caller can see: the ordered, role-
    keyed registry of agent class names."""
    return [
        (role, type(agent).__name__)
        for role, agent in coord.registry.agents.items()
    ]


# Corpus: every keyword that drives a branch, the broad triggers, combinations,
# empties, and substrings that should NOT trigger (to lock negative paths).
_KEYWORDS = [
    "security",
    "docstring",
    "semantic",
    "test",
    "coverage",
    "dependency",
    "project_scan",
    "full",
    "self",
]


def _plan_corpus() -> list[str]:
    plans: list[str] = [
        "",
        "noop",
        "unknown_plan",
        "secur",        # near-miss, must not trigger
        "depend",       # near-miss, must not trigger
        "full_autonomous_loop",
        "semantic_patch_loop",
        "project_scan",
        "security_audit",
        "self_improve",
        "test_coverage_sweep",
        "dependency_check",
        "docstring_pass",
        "security_test_dependency",
        "full security docstring test dependency semantic coverage self project_scan",
    ]
    # Add each single keyword and every adjacent pair to exhaust branches.
    plans.extend(_KEYWORDS)
    plans.extend(f"{a}_{b}" for a, b in itertools.combinations(_KEYWORDS, 2))
    return plans


def test_build_swarm_byte_identical_over_corpus():
    mismatches = []
    for plan in _plan_corpus():
        for use_fractal in (False, True):
            ref = _observable(_original_build_swarm_for_plan(plan, use_fractal))
            got = _observable(_build_swarm_for_plan(plan, use_fractal))
            if ref != got:
                mismatches.append((plan, use_fractal, ref, got))
    assert not mismatches, f"Behavior diverged: {mismatches[:5]}"


def test_corpus_covers_every_branch():
    """Guard: the corpus must actually exercise empty, single, and full
    selections so the byte-identical proof is meaningful."""
    sizes = {
        len(_observable(_build_swarm_for_plan(p, False))) for p in _plan_corpus()
    }
    assert 0 in sizes        # empty selection reachable
    assert max(sizes) >= 4   # all four scanners reachable


def test_fractal_swaps_classes():
    """Every selected scanner has its fractal variant swapped in under fractal
    mode, and the plain variant otherwise (locks the conditional expressions)."""
    plain = {
        t for _, t in _observable(_build_swarm_for_plan("full", False))
    }
    fractal = {
        t for _, t in _observable(_build_swarm_for_plan("full", True))
    }
    assert "SecurityAgent" in plain and "FractalSecurityAgent" in fractal
    assert "DocstringAgent" in plain and "FractalDocstringAgent" in fractal
    assert "TestStubAgent" in plain and "FractalTestStubAgent" in fractal
    # DependencyAgent has no fractal variant: present in both.
    assert "DependencyAgent" in plain and "DependencyAgent" in fractal
