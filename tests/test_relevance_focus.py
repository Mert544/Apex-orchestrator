from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.relevance_scorer import RelevanceScorer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator


def _make_orchestrator(focus=None, max_depth=2):
    config = {
        "max_depth": max_depth,
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
    # With pruning enabled, off-topic branches that drift below the relevance
    # threshold are stopped. This objective reliably spawns lower-relevance
    # sibling claims at depth >= 1 that the drift cut removes.
    orch = _make_orchestrator(focus={"min_relevance": 0.8, "min_depth": 1})
    report = orch.run("Investigate database query performance and indexing")
    assert report.debug_stats["focus_drift_pruned"] >= 1
    # The run still completes and returns a usable report.
    assert report.objective == "Investigate database query performance and indexing"


def test_pruning_off_does_not_prune_same_objective():
    # The same objective with pruning disabled removes nothing (sanity check
    # that the prune is what's doing the work, not termination).
    orch = _make_orchestrator()  # no focus config -> pruning off
    report = orch.run("Investigate database query performance and indexing")
    assert report.debug_stats["focus_drift_pruned"] == 0


def test_concept_expansion_matches_related_grounding():
    from app.skills.relevance_scorer import RelevanceScorer
    r = RelevanceScorer("improve the security of the bank")
    # A harden/finding-grounded idea scores > 0 for a "security" objective even
    # though "security" never appears in its text — via concept expansion.
    assert r.score("Harden the sensitive path app/accounts.py security-finding") > 0.0
    # An unrelated idea stays at 0.
    assert r.score("Add type hints and a lint config") == 0.0


def test_concept_expansion_does_not_break_pruning():
    from app.skills.relevance_scorer import RelevanceScorer
    # An unrelated objective must still prune a generic idea (no false matches).
    r = RelevanceScorer("database indexing performance")
    assert r.score("Evolve the central module app/main.py") == 0.0


def test_no_objective_is_all_relevant():
    from app.skills.relevance_scorer import RelevanceScorer
    assert RelevanceScorer("").score("anything at all") == 1.0
