from app.memory.graph_store import GraphStore


def test_graph_store_question_dedup():
    graph = GraphStore()
    q = "What is missing?"
    assert graph.has_similar_question(q) is False
    graph.register_question(q)
    assert graph.has_similar_question(q) is True
