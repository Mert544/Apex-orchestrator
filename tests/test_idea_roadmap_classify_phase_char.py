"""Characterization proof that the refactored ``classify_phase`` is byte-identical
to the pre-refactor original across an exhaustive cross-product of inputs.

The original implementation is reconstructed verbatim below as ``_classify_phase_original``
so the proof is self-contained (it does not depend on git state at test time).
Every branch of the dispatch tree is exercised: all kinds, all operators, an
empty/unknown operator, representative labels from each phase label-set, plus
convergence/theme source-fact combinations and empty/missing operator_chains.
"""

from __future__ import annotations

import itertools

from app.engine import idea_roadmap as R
from app.engine.idea_roadmap import (
    EVOLVE,
    REFINE,
    SECURE,
    STABILIZE,
    classify_phase,
)
from app.models.idea import IdeaNode


def _classify_phase_original(node: IdeaNode) -> str:
    """Verbatim copy of the pre-refactor ``classify_phase`` body."""
    label = node.source_facts[0].split(":")[0].strip() if node.source_facts else ""
    op = node.operator

    if node.kind == "synthesis":
        if any(f.startswith("convergence:") for f in node.source_facts):
            return STABILIZE
        if any(f.startswith("theme:") for f in node.source_facts):
            lens = node.operator_chain[-1] if node.operator_chain else ""
            if lens == "test":
                return STABILIZE
            if lens == "harden":
                return SECURE
            if lens in R._REFINE_OPS:
                return REFINE
            return EVOLVE
        return SECURE
    if node.kind == "pair":
        return EVOLVE

    if op == "test" or label in R._STABILIZE_LABELS:
        if op in R._REFINE_OPS:
            return REFINE
        if op in R._EVOLVE_OPS:
            return EVOLVE
        return STABILIZE
    if op == "harden" or label in R._SECURE_LABELS:
        return SECURE
    if op in R._EVOLVE_OPS or label in R._EVOLVE_LABELS:
        return EVOLVE
    if op in R._REFINE_OPS or label in R._REFINE_LABELS:
        return REFINE
    return EVOLVE


def _representative_labels() -> list[str]:
    labels: set[str] = {"", "unknown-label"}
    for s in (
        R._STABILIZE_LABELS,
        R._SECURE_LABELS,
        R._EVOLVE_LABELS,
        R._REFINE_LABELS,
        R._HIGH_IMPACT_LABELS,
    ):
        labels.update(sorted(s)[:3])
    return sorted(labels)


def _representative_operators() -> list[str]:
    ops: set[str] = {"", "root", "test", "harden", "unknown-op"}
    ops.update(R._REFINE_OPS)
    ops.update(R._EVOLVE_OPS)
    return sorted(ops)


def _source_fact_variants(label: str) -> list[list[str]]:
    base: list[str] = []
    if label:
        base = [f"{label}: some detail"]
    return [
        base,
        base + ["convergence: a+b+c"],
        base + ["theme: x (3 modules)"],
        base + ["dependency-cycle: a -> b"],
        ["convergence: a+b"] + base,
        ["theme: y (1 modules)"] + base,
    ]


def _chain_variants() -> list[list[str]]:
    return [
        [],
        ["test"],
        ["harden"],
        ["document"],
        ["observe"],
        ["simplify"],
        ["extend"],
        ["generalize"],
        ["integrate"],
        ["unknown-lens"],
        ["test", "harden"],
        ["harden", "document"],
    ]


def _all_nodes() -> list[IdeaNode]:
    kinds = ["permutation", "synthesis", "pair", "facet", "weird-kind"]
    labels = _representative_labels()
    ops = _representative_operators()
    chains = _chain_variants()
    nodes: list[IdeaNode] = []
    n = 0
    for kind, label, op, chain in itertools.product(kinds, labels, ops, chains):
        for facts in _source_fact_variants(label):
            n += 1
            nodes.append(
                IdeaNode(
                    id=f"n{n}",
                    title="t",
                    subject="m",
                    kind=kind,
                    operator=op,
                    operator_chain=list(chain),
                    source_facts=list(facts),
                )
            )
    return nodes


def test_classify_phase_byte_identical_to_original():
    nodes = _all_nodes()
    assert len(nodes) > 5000  # exhaustive cross-product, every branch covered
    mismatches = []
    for node in nodes:
        got = classify_phase(node)
        want = _classify_phase_original(node)
        if got != want:
            mismatches.append((node.kind, node.operator, node.operator_chain, node.source_facts, got, want))
    assert mismatches == [], f"{len(mismatches)} mismatches, e.g. {mismatches[:3]}"
    # Every classification is one of the four legal phases.
    assert {classify_phase(n) for n in nodes} <= {STABILIZE, SECURE, EVOLVE, REFINE}


def test_classify_phase_each_phase_reachable():
    seen = {classify_phase(n) for n in _all_nodes()}
    assert seen == {STABILIZE, SECURE, EVOLVE, REFINE}


def test_helpers_are_pure_and_deterministic():
    node = IdeaNode(
        id="x", title="t", kind="synthesis",
        source_facts=["theme: z (2 modules)"], operator_chain=["harden"],
    )
    a = classify_phase(node)
    b = classify_phase(node)
    assert a == b == SECURE


def test_empty_synthesis_no_facts_secure():
    node = IdeaNode(id="e", title="t", kind="synthesis", source_facts=[])
    assert classify_phase(node) == SECURE


def test_pair_always_evolve():
    for facts in ([], ["convergence: a+b"], ["theme: t (9 modules)"], ["untested: x"]):
        node = IdeaNode(id="p", title="t", kind="pair", source_facts=list(facts))
        assert classify_phase(node) == EVOLVE
