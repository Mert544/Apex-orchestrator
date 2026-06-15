from __future__ import annotations

from app.memory.graph_store import GraphStore
from app.models.enums import ClaimType, NodeStatus
from app.models.node import ResearchNode


def _node(node_id: str, claim: str, branch: str) -> ResearchNode:
    return ResearchNode(
        id=node_id,
        claim=claim,
        branch_path=branch,
        claim_type=ClaimType.ARCHITECTURE,
        claim_priority=0.5,
        confidence=0.6,
        risk=0.3,
        status=NodeStatus.EXPANDED,
    )


def test_empty_graph_reports_zero():
    store = GraphStore()
    assert store.size() == 0
    assert store.get_all_nodes() == []
    assert list(store.iter_all_nodes()) == []
    assert store.branch_map() == {}


def test_add_node_registers_claim_and_updates_views():
    store = GraphStore()
    store.add_node(_node("n1", "Central Claim", "x.a"))
    assert store.size() == 1
    assert store.has_similar_claim("central claim") is True
    assert store.branch_map() == {"x.a": "Central Claim"}
    assert [n.id for n in store.iter_all_nodes()] == ["n1"]


def test_register_claim_and_question_ignore_blank():
    store = GraphStore()
    store.register_claim("   ")
    store.register_question("")
    assert store.has_similar_claim("   ") is False
    assert store.has_similar_question("") is False


def test_load_memory_claim_and_question_are_case_insensitive():
    store = GraphStore()
    store.load_memory_claim("  Known Claim  ")
    store.load_memory_question("  Known Question?  ")
    assert store.has_memory_claim("known claim") is True
    assert store.has_memory_question("KNOWN QUESTION?") is True
    # Blank inputs are dropped, not stored.
    store.load_memory_claim("   ")
    assert store.has_memory_claim("") is False


def test_memory_and_observed_sets_are_independent():
    store = GraphStore()
    store.add_node(_node("n1", "Observed", "x.a"))
    store.load_memory_claim("Remembered")
    # Observed claims are not memory claims and vice versa.
    assert store.has_similar_claim("observed") is True
    assert store.has_memory_claim("observed") is False
    assert store.has_memory_claim("remembered") is True
    assert store.has_similar_claim("remembered") is False


def test_branch_map_skips_nodes_without_branch_path():
    store = GraphStore()
    store.add_node(_node("n1", "Has Branch", "x.a"))
    store.add_node(_node("n2", "No Branch", ""))
    bm = store.branch_map()
    assert bm == {"x.a": "Has Branch"}
