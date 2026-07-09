"""NoveltyScorer — branch precedence guards (eyml2 wave).

The line coverage of ``novelty`` is already complete; these tests pin the
ORDERING of the three-way branches (similar beats memory beats novel) so a future
reordering of the checks is caught. Deterministic, offline.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.engine.novelty import NoveltyScorer
from app.memory.graph_store import GraphStore


def test_question_similar_beats_memory():
    # A question that is BOTH a live similar question AND recalled from memory
    # must score 0.0 — the similar check is consulted first.
    graph = GraphStore()
    graph.register_question("shared question")
    graph.load_memory_question("shared question")
    scorer = NoveltyScorer(graph)
    assert scorer.score_question("shared question") == 0.0


def test_node_similar_beats_memory():
    graph = GraphStore()
    graph.register_claim("shared claim")
    graph.load_memory_claim("shared claim")
    scorer = NoveltyScorer(graph)
    assert scorer.score_node(SimpleNamespace(claim="shared claim")) == 0.0


def test_question_scores_are_monotone_by_familiarity():
    # novel (1.0) > memory (0.25) > similar (0.0): the score shrinks as the graph
    # grows more familiar with the text.
    novel = NoveltyScorer(GraphStore()).score_question("fresh")
    mem_graph = GraphStore()
    mem_graph.load_memory_question("recalled")
    memory = NoveltyScorer(mem_graph).score_question("recalled")
    sim_graph = GraphStore()
    sim_graph.register_question("known")
    similar = NoveltyScorer(sim_graph).score_question("known")
    assert novel > memory > similar
