from __future__ import annotations

from types import SimpleNamespace

from app.engine.novelty import NoveltyScorer
from app.memory.graph_store import GraphStore


def test_score_question_novel_returns_one():
    # No similar and no memory question -> fully novel (line 13: return 1.0).
    scorer = NoveltyScorer(GraphStore())
    assert scorer.score_question("a brand new question") == 1.0


def test_score_question_similar_returns_zero():
    graph = GraphStore()
    graph.register_question("known question")
    scorer = NoveltyScorer(graph)
    assert scorer.score_question("known question") == 0.0


def test_score_question_memory_returns_quarter():
    graph = GraphStore()
    graph.load_memory_question("recalled question")
    scorer = NoveltyScorer(graph)
    assert scorer.score_question("recalled question") == 0.25


def test_score_node_similar_returns_zero():
    # Claim already registered as a live claim (line 17: return 0.0).
    graph = GraphStore()
    graph.register_claim("the sky is blue")
    scorer = NoveltyScorer(graph)
    assert scorer.score_node(SimpleNamespace(claim="the sky is blue")) == 0.0


def test_score_node_memory_returns_quarter():
    graph = GraphStore()
    graph.load_memory_claim("remembered claim")
    scorer = NoveltyScorer(graph)
    assert scorer.score_node(SimpleNamespace(claim="remembered claim")) == 0.25


def test_score_node_novel_returns_default():
    # No similar and no memory claim -> default novelty (line 20: return 0.85).
    scorer = NoveltyScorer(GraphStore())
    assert scorer.score_node(SimpleNamespace(claim="never seen before")) == 0.85
