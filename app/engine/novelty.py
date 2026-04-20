from app.memory.graph_store import GraphStore


class NoveltyScorer:
    def __init__(self, graph: GraphStore) -> None:
        self.graph = graph

    def score_question(self, question_text: str) -> float:
        return 0.0 if self.graph.has_similar_question(question_text) else 1.0

    def score_node(self, node) -> float:
        if any(existing.claim.strip().lower() == node.claim.strip().lower() for existing in self.graph.get_all_nodes() if existing.id != node.id):
            return 0.0
        return 0.85
