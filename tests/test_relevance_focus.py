from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.relevance_scorer import RelevanceScorer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator


def _make_orchestrator(focus=None):
    config = {
        "max_depth": 2,
        "max_total_nodes": 12,
        "top_k_questions": 2,
        "min_security": 0.8,
        "min_quality": 0.6,
        "min_novelty": 0.2,
    }
    if focus is not None:
        config["focus"] = focus
    return FractalResearchOrchestrator(
        config=config,
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
    )


# --- RelevanceScorer (deterministic, no LLM) --------------------------------

def test_relevance_no_objective_is_fully_relevant():
    scorer = RelevanceScorer("")
    assert scorer.score("anything at all") == 1.0


def test_relevance_on_topic_beats_off_topic():
    scorer = RelevanceScorer("improve database query performance and indexing")
    on_topic = scorer.score("the database index speeds up query performance")
    off_topic = scorer.score("the marketing newsletter signup form colours")
    assert on_topic > off_topic
    assert off_topic == 0.0
    assert 0.0 < on_topic <= 1.0


def test_relevance_is_deterministic():
    scorer = RelevanceScorer("focus on the main idea of the reasoning tree")
    text = "the reasoning tree should stay on the main idea"
    assert scorer.score(text) == scorer.score(text)


# --- Orchestrator integration -----------------------------------------------

def test_run_records_mean_relevance_observability():
    orch = _make_orchestrator()
    report = orch.run("Investigate the CI pipeline and test coverage")
    assert "mean_relevance" in report.debug_stats
    assert 0.0 <= report.debug_stats["mean_relevance"] <= 1.0
    assert "focus_drift_pruned" in report.debug_stats


def test_nodes_carry_relevance_scores():
    orch = _make_orchestrator()
    orch.run("Investigate the CI pipeline and test coverage")
    nodes = orch.graph.get_all_nodes()
    assert nodes
    assert all(0.0 <= n.relevance <= 1.0 for n in nodes)


def test_pruning_off_by_default_keeps_behaviour():
    orch = _make_orchestrator()  # no focus config
    report = orch.run("Investigate the CI pipeline and test coverage")
    assert report.debug_stats["focus_drift_pruned"] == 0
    assert len(report.main_findings) >= 1


def test_pruning_can_be_enabled_via_config():
    # A very high threshold prunes any branch that is not near-perfectly on topic.
    orch = _make_orchestrator(focus={"min_relevance": 0.99, "min_depth": 1})
    report = orch.run("Investigate the CI pipeline and test coverage")
    # Enabling the drift cut should stop at least one off-topic branch.
    assert report.debug_stats["focus_drift_pruned"] >= 1
    # The run still completes and returns a usable report.
    assert report.objective == "Investigate the CI pipeline and test coverage"
