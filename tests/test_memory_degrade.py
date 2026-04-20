from app.engine.novelty import NoveltyScorer
from app.memory.graph_store import GraphStore
from app.skills.spam_guard import SpamGuard


class DummyNode:
    def __init__(self, claim: str, node_id: str = "n1") -> None:
        self.claim = claim
        self.id = node_id


def test_novelty_scorer_degrades_memory_questions_instead_of_blocking():
    graph = GraphStore()
    graph.load_memory_question("What evidence would directly contradict this claim?")
    scorer = NoveltyScorer(graph)

    assert scorer.score_question("What evidence would directly contradict this claim?") == 0.25
    graph.register_question("What evidence would directly contradict this claim?")
    assert scorer.score_question("What evidence would directly contradict this claim?") == 0.0


def test_novelty_scorer_degrades_memory_claims_instead_of_blocking():
    graph = GraphStore()
    graph.load_memory_claim("Dependency hub claim")
    scorer = NoveltyScorer(graph)
    node = DummyNode("Dependency hub claim")

    assert scorer.score_node(node) == 0.25
    graph.register_claim("Dependency hub claim")
    assert graph.has_similar_claim("Dependency hub claim") is True


def test_spam_guard_still_blocks_nested_meta_noise():
    guard = SpamGuard()
    noisy = "Missing-information claim: missing-information claim: dependency hub claim around app/services/order_service.py."
    assert guard.is_low_value_claim(noisy, parent_claim=None) is True
