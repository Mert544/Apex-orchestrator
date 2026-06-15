from __future__ import annotations

import json
from pathlib import Path

from app.memory.persistent_memory import PersistentMemoryStore
from app.models.enums import ClaimType, NodeStatus
from app.models.node import ResearchNode
from app.models.report import FinalReport


def _make_node(claim: str, branch: str, priority: float) -> ResearchNode:
    return ResearchNode(
        id=f"n-{branch}",
        claim=claim,
        branch_path=branch,
        claim_type=ClaimType.ARCHITECTURE,
        claim_priority=priority,
        confidence=0.7,
        risk=0.3,
        status=NodeStatus.EXPANDED,
    )


def test_load_state_returns_default_when_file_missing(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    state = store.load_state()
    assert state["known_claims"] == []
    assert state["known_questions"] == []
    assert state["last_full_report"] == {}


def test_load_state_uses_cache_on_second_call(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    first = store.load_state()
    second = store.load_state()
    # Cached: identical object returned (covers the cache short-circuit branch).
    assert first is second


def test_load_state_recovers_from_corrupt_json(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    store.memory_dir.mkdir(parents=True, exist_ok=True)
    store.memory_file.write_text("{not valid json", encoding="utf-8")
    state = store.load_state()
    # Falls through the except branch back to default.
    assert state["known_claims"] == []
    assert state["schema_version"] == 1


def test_load_state_recovers_from_non_dict_json(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    store.memory_dir.mkdir(parents=True, exist_ok=True)
    store.memory_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    state = store.load_state()
    # A JSON list is valid JSON but not a dict -> default.
    assert isinstance(state, dict)
    assert state["known_questions"] == []


def test_load_state_adds_missing_last_full_report_key(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    store.memory_dir.mkdir(parents=True, exist_ok=True)
    store.memory_file.write_text(
        json.dumps({"schema_version": 1, "known_claims": ["a"]}), encoding="utf-8"
    )
    state = store.load_state()
    assert state["last_full_report"] == {}
    assert state["known_claims"] == ["a"]


def test_estimated_bytes_reflects_state_size(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    empty_size = store.estimated_bytes()
    assert empty_size > 0
    # After persisting a run the serialized state should be larger.
    report = FinalReport(
        objective="demo",
        confidence_map={"some claim text": 0.8},
        unresolved_questions=["what about x?"],
        main_findings=["some claim text"],
        recommended_actions=["do the thing"],
        branch_map={"x.a": "some claim text"},
    )
    store.persist_run("demo", report, [_make_node("some claim text", "x.a", 0.9)])
    assert store.estimated_bytes() > empty_size


def test_hydrate_graph_tolerates_none_graph(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    store.memory_dir.mkdir(parents=True, exist_ok=True)
    store.memory_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "known_claims": ["c1"],
                "known_questions": ["q1"],
            }
        ),
        encoding="utf-8",
    )
    state = store.hydrate_graph(None)
    assert state["known_claims"] == ["c1"]


def test_dedupe_drops_blank_and_case_insensitive_duplicates(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    cleaned = store._dedupe(["Claim A", "claim a", "  ", "", "Claim B"])
    # First-seen casing preserved; blanks and case-dupes dropped.
    assert cleaned == ["Claim A", "Claim B"]


def test_persist_run_evicts_when_over_count_limit(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path, max_claims=3, max_questions=3)
    store.memory_dir.mkdir(parents=True, exist_ok=True)
    seed = {
        "schema_version": 1,
        "known_claims": [f"claim {i}" for i in range(10)],
        "known_questions": [f"question {i}" for i in range(10)],
        "runs": [],
        "branch_history": [],
        "last_report": {},
        "last_full_report": {},
    }
    store.memory_file.write_text(json.dumps(seed), encoding="utf-8")
    store._state_cache = None

    report = FinalReport(
        objective="demo",
        confidence_map={"fresh claim": 0.6},
        unresolved_questions=["fresh question?"],
        main_findings=["fresh claim"],
        recommended_actions=["act"],
        branch_map={"x.a": "fresh claim"},
    )
    summary = store.persist_run("demo", report, [_make_node("fresh claim", "x.a", 0.9)])
    state = store.load_state()
    # Eviction trims to max + the newly-added unique items.
    assert len(state["known_claims"]) <= store.max_claims + 1
    assert summary["known_claim_count"] == len(state["known_claims"])


def test_persist_run_size_based_eviction_trims_branch_history(tmp_path: Path):
    # Tiny size budget forces the secondary (size-based) eviction path.
    store = PersistentMemoryStore(
        project_root=tmp_path,
        max_claims=400,
        max_questions=400,
        max_state_size_mb=0.0005,
    )
    store.memory_dir.mkdir(parents=True, exist_ok=True)
    seed = {
        "schema_version": 1,
        "known_claims": [f"claim number {i} with padding text" for i in range(400)],
        "known_questions": [f"question number {i} with padding text" for i in range(400)],
        "runs": [],
        "branch_history": [{"branch_path": f"b{i}", "claim": "c"} for i in range(300)],
        "last_report": {},
        "last_full_report": {},
    }
    store.memory_file.write_text(json.dumps(seed), encoding="utf-8")
    store._state_cache = None

    nodes = [_make_node(f"node claim {i}", f"x.{i}", float(i)) for i in range(150)]
    report = FinalReport(
        objective="demo",
        confidence_map={"new claim": 0.6},
        unresolved_questions=["new q?"],
        main_findings=["new claim"],
        recommended_actions=["act"],
        branch_map={"x.0": "node claim 0"},
    )
    store.persist_run("demo", report, nodes)
    state = store.load_state()
    # Size-based eviction fires on the oversized seed: known_claims is trimmed
    # well below the count limit (down toward the per-collection floor of 10).
    assert len(state["known_claims"]) < 400
    assert len(state["known_questions"]) < 400
    # branch_history is rebuilt from the run's nodes (capped at 250 in persist_run).
    assert len(state["branch_history"]) == len(nodes)


def test_persist_run_focused_does_not_overwrite_last_full_report(tmp_path: Path):
    store = PersistentMemoryStore(project_root=tmp_path)
    full = FinalReport(
        objective="demo",
        confidence_map={"full claim": 0.8},
        main_findings=["full claim"],
        branch_map={"x.a": "full claim"},
    )
    store.persist_run("demo", full, [_make_node("full claim", "x.a", 0.9)])

    focused = FinalReport(
        objective="demo",
        confidence_map={"focused claim": 0.8},
        main_findings=["focused claim"],
        branch_map={"x.b": "focused claim"},
        focus_branch="x.b",
    )
    store.persist_run("demo", focused, [_make_node("focused claim", "x.b", 0.9)])
    state = store.load_state()
    # last_full_report retains the full run; last_report reflects the focused one.
    assert state["last_full_report"]["main_findings"] == ["full claim"]
    assert state["last_report"]["main_findings"] == ["focused claim"]
    assert state["runs"][-1]["run_mode"] == "focused"
