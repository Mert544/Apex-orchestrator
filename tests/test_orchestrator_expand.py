"""Behavioral tests for FractalResearchOrchestrator._expand — the engine's
highest-complexity, previously test-unnamed function (an Apex hotspot-function
idea, dogfooded). Each test drives one distinct branch of _expand directly.
"""

from app.models.enums import NodeStatus, StopReason
from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.relevance_scorer import RelevanceScorer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator


def _orch(**overrides):
    config = {
        "max_depth": 2,
        "max_total_nodes": 50,
        "top_k_questions": 2,
        "min_security": 0.8,
        "min_quality": 0.6,
        "min_novelty": 0.2,
    }
    config.update(overrides)
    return FractalResearchOrchestrator(
        config=config,
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
    )


def _root(orch, claim="The system should validate all untrusted input thoroughly.", depth=0):
    return orch.node_factory.make_node(id="root", claim=claim, depth=depth, branch_path="x")


def test_expand_analyzes_node_and_grows_the_graph():
    orch = _orch()
    orch.relevance_scorer = RelevanceScorer("validate untrusted input")
    node = _root(orch)
    before = len(orch.graph.get_all_nodes())

    orch._expand(node)

    # The node carries a full analysis after expansion.
    assert isinstance(node.evidence_for, list)
    assert isinstance(node.evidence_against, list)
    assert node.assumptions                      # always at least the extractor's
    assert node.questions                        # questions were generated
    assert 0.0 <= node.confidence <= 1.0
    assert 0.0 <= node.risk <= 1.0
    # A healthy expansion either spawned children or stopped for a named reason.
    if node.status == NodeStatus.STOPPED:
        assert node.stop_reason is not None
    else:
        assert len(orch.graph.get_all_nodes()) > before


def test_expand_prunes_off_topic_node_under_focus():
    orch = _orch()
    # Focus filter on; this node's claim is unrelated to the objective.
    orch.focus_min_relevance = 0.99
    orch.focus_min_depth = 0
    orch.relevance_scorer = RelevanceScorer("quantum chromodynamics lattice gauge theory")
    node = _root(orch, claim="Bake a chocolate cake with vanilla frosting.", depth=1)

    drift_before = orch.debug_stats["focus_drift_pruned"]
    orch._expand(node)

    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason == StopReason.FOCUS_DRIFT
    assert orch.debug_stats["focus_drift_pruned"] == drift_before + 1


def test_expand_stops_before_expansion_at_max_depth():
    orch = _orch(max_depth=2)
    orch.relevance_scorer = RelevanceScorer("validate input")
    node = _root(orch, depth=2)          # depth >= max_depth -> pre-expansion stop

    orch._expand(node)

    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason == StopReason.MAX_DEPTH


def test_expand_stops_before_expansion_when_budget_exhausted():
    orch = _orch(max_total_nodes=1)
    orch.relevance_scorer = RelevanceScorer("validate input")
    # Exhaust the budget so the pre-expansion guard trips.
    while not orch.budget.exhausted:
        orch.budget.consume_node()
    node = _root(orch, depth=0)

    orch._expand(node)

    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason == StopReason.BUDGET_EXHAUSTED


def test_expand_enforces_low_security_stop_after_scoring():
    # An impossibly high security bar makes should_stop_after_scoring fire, so a
    # scored node is stopped before it can spawn children.
    orch = _orch(min_security=1.01)
    orch.relevance_scorer = RelevanceScorer("validate input")
    node = _root(orch)

    orch._expand(node)

    assert node.status == NodeStatus.STOPPED
    assert node.stop_reason in (StopReason.LOW_SECURITY, StopReason.LOW_QUALITY, StopReason.LOW_NOVELTY)
