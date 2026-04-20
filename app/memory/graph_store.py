from app.models.node import ResearchNode


class GraphStore:
    def __init__(self) -> None:
        self.nodes: dict[str, ResearchNode] = {}
        self.question_texts: set[str] = set()

    def add_node(self, node: ResearchNode) -> None:
        self.nodes[node.id] = node

    def has_similar_question(self, qtext: str) -> bool:
        return qtext.strip().lower() in self.question_texts

    def register_question(self, qtext: str) -> None:
        self.question_texts.add(qtext.strip().lower())

    def get_all_nodes(self) -> list[ResearchNode]:
        return list(self.nodes.values())
