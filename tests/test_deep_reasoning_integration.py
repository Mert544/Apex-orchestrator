"""Integration tests: the previously-orphaned reasoning engines are now wired.

CounterfactualGenerator and ConfidenceCalibrator (app/engine/*) used to be
implemented and unit-tested but never called in the live pipeline. These tests
lock in that the orchestrator actually exercises them.
"""
from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator


def _make(deep):
    cfg = {
        "max_depth": 2,
        "max_total_nodes": 12,
        "top_k_questions": 2,
        "min_security": 0.8,
        "min_quality": 0.6,
        "min_novelty": 0.2,
        "reasoning": {"deep": deep},
    }
    return FractalResearchOrchestrator(
        config=cfg,
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
    )


def test_deep_reasoning_on_by_default():
    orch = _make(deep=True)
    report = orch.run("The eval() call on user input is a security risk")
    assert report.debug_stats["counterfactuals_generated"] >= 1
    assert report.debug_stats["calibrated_nodes"] >= 1


def test_nodes_get_counterfactuals_and_reliability():
    orch = _make(deep=True)
    orch.run("The eval() call on user input needs validation")
    nodes = orch.graph.get_all_nodes()
    assert any(n.counterfactuals for n in nodes)
    assert any(n.confidence_reliability in {"low", "medium", "high"} for n in nodes)


def test_deep_reasoning_can_be_disabled():
    orch = _make(deep=False)
    report = orch.run("The eval() call on user input is a security risk")
    assert report.debug_stats["counterfactuals_generated"] == 0
    assert report.debug_stats["calibrated_nodes"] == 0
    nodes = orch.graph.get_all_nodes()
    assert all(not n.counterfactuals for n in nodes)
