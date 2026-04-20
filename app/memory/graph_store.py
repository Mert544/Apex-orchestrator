from app.models.node import ResearchNode


class GraphStore:
    def __init__(self) -> None:
        self.nodes: dict[str, ResearchNode] = {}
        self.question_texts: set[str] = set()
        self.claim_texts: set[str] = set()
        self.memory_question_texts: set[str] = set()
        self.memory_claim_texts: set[str] = set()

    def add_node(self, node: ResearchNode) -> None:
        self.nodes[node.id] = node
        self.register_claim(node.claim)

    def load_memory_claim(self, claim: str) -> None:
        cleaned = claim.strip().lower()
        if cleaned:
            self.memory_claim_texts.add(cleaned)

    def load_memory_question(self, qtext: str) -> None:
        cleaned = qtext.strip().lower()
        if cleaned:
            self.memory_question_texts.add(cleaned)

    def has_similar_question(self, qtext: str) -> bool:
        return qtext.strip().lower() in self.question_texts

    def has_memory_question(self, qtext: str) -> bool:
        return qtext.strip().lower() in self.memory_question_texts

    def register_question(self, qtext: str) -> None:
        cleaned = qtext.strip().lower()
        if cleaned:
            self.question_texts.add(cleaned)

    def has_similar_claim(self, claim: str) -> bool:
        return claim.strip().lower() in self.claim_texts

    def has_memory_claim(self, claim: str) -> bool:
        return claim.strip().lower() in self.memory_claim_texts

    def register_claim(self, claim: str) -> None:
        cleaned = claim.strip().lower()
        if cleaned:
            self.claim_texts.add(cleaned)

    def get_all_nodes(self) -> list[ResearchNode]:
        return list(self.nodes.values())
