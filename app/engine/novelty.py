from app.memory.graph_store import GraphStore


class NoveltyScorer:
    def __init__(self, graph: GraphStore) -> None:
        self.graph = graph

    def score_question(self, question_text: str) -> float:
        if self.graph.has_similar_question(question_text):
            return 0.0
        if self.graph.has_memory_question(question_text):
            return 0.25
        return 1.0

    def score_node(self, node) -> float:
        if self.graph.has_similar_claim(node.claim):
            return 0.0
        if self.graph.has_memory_claim(node.claim):
            return 0.25
        return 0.85
