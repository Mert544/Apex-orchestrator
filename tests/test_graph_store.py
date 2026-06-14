from __future__ import annotations

from app.memory.graph_store import GraphStore
from app.models.node import ResearchNode


def _node(node_id: str, claim: str, branch_path: str = "") -> ResearchNode:
    return ResearchNode(id=node_id, claim=claim, branch_path=branch_path)


class TestGraphStoreNodes:
    def test_add_node_indexes_and_registers_claim(self):
        store = GraphStore()
        node = _node("n1", "Dependency Hub Claim")

        store.add_node(node)

        assert store.nodes["n1"] is node
        assert store.size() == 1
        # add_node calls register_claim, normalizing to lowercase.
        assert store.has_similar_claim("dependency hub claim") is True
        assert store.has_similar_claim("  DEPENDENCY HUB CLAIM  ") is True

    def test_get_all_nodes_returns_copy(self):
        store = GraphStore()
        node = _node("n1", "claim a")
        store.add_node(node)

        nodes = store.get_all_nodes()
        nodes.append(_node("n2", "claim b"))

        # Mutating the returned list must not affect internal state.
        assert store.size() == 1
        assert len(store.get_all_nodes()) == 1

    def test_iter_all_nodes_yields_in_insertion_order(self):
        store = GraphStore()
        first = _node("n1", "first claim")
        second = _node("n2", "second claim")
        store.add_node(first)
        store.add_node(second)

        yielded = list(store.iter_all_nodes())
        assert [n.id for n in yielded] == ["n1", "n2"]

    def test_size_empty_store_is_zero(self):
        assert GraphStore().size() == 0


class TestGraphStoreClaims:
    def test_register_claim_ignores_blank(self):
        store = GraphStore()
        store.register_claim("   ")
        store.register_claim("")
        assert store.claim_texts == set()
        assert store.has_similar_claim("") is False

    def test_register_claim_normalizes_case_and_whitespace(self):
        store = GraphStore()
        store.register_claim("  Some Claim  ")
        assert "some claim" in store.claim_texts
        assert store.has_similar_claim("SOME CLAIM") is True
        assert store.has_similar_claim("other claim") is False

    def test_memory_claim_separate_from_live_claim(self):
        store = GraphStore()
        store.load_memory_claim("  Recalled Claim  ")

        assert store.has_memory_claim("recalled claim") is True
        # A memory claim is not a live registered claim.
        assert store.has_similar_claim("recalled claim") is False

    def test_load_memory_claim_ignores_blank(self):
        store = GraphStore()
        store.load_memory_claim("")
        store.load_memory_claim("   ")
        assert store.memory_claim_texts == set()
        assert store.has_memory_claim("") is False


class TestGraphStoreQuestions:
    def test_register_question_normalizes_and_matches(self):
        store = GraphStore()
        store.register_question("  Why Does X Fail?  ")
        assert store.has_similar_question("why does x fail?") is True
        assert store.has_similar_question("unrelated question") is False

    def test_register_question_ignores_blank(self):
        store = GraphStore()
        store.register_question("")
        store.register_question("   ")
        assert store.question_texts == set()

    def test_memory_question_separate_from_live_question(self):
        store = GraphStore()
        store.load_memory_question("  Recalled Question?  ")

        assert store.has_memory_question("recalled question?") is True
        assert store.has_similar_question("recalled question?") is False

    def test_load_memory_question_ignores_blank(self):
        store = GraphStore()
        store.load_memory_question("")
        store.load_memory_question("   ")
        assert store.memory_question_texts == set()
        assert store.has_memory_question("") is False


class TestGraphStoreBranchMap:
    def test_branch_map_maps_branch_path_to_claim(self):
        store = GraphStore()
        store.add_node(_node("n1", "claim a", branch_path="root.a"))
        store.add_node(_node("n2", "claim b", branch_path="root.b"))

        bmap = store.branch_map()
        assert bmap == {"root.a": "claim a", "root.b": "claim b"}

    def test_branch_map_skips_nodes_without_branch_path(self):
        store = GraphStore()
        store.add_node(_node("n1", "no branch"))  # branch_path defaults to ""
        store.add_node(_node("n2", "has branch", branch_path="root.x"))

        bmap = store.branch_map()
        assert bmap == {"root.x": "has branch"}

    def test_branch_map_empty_store_is_empty(self):
        assert GraphStore().branch_map() == {}
