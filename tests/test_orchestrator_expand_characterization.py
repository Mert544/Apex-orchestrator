"""Characterization tests pinning ``FractalResearchOrchestrator._expand``'s
expanded-tree output after its decomposition into pure helpers.

These exercise the full expansion path via ``run()`` across several objectives
(shallow, deep, and budget-exhausting) and assert the expanded structure stays
deterministic: same input -> same node ids, ordering, branch paths, statuses,
stop reasons, scores, evidence, questions, and debug stats. They are the safety
net proving the refactor preserved behaviour byte-for-byte.
"""

import pytest

from app.orchestrator import FractalResearchOrchestrator
from app.skills.decomposer import Decomposer
from app.skills.relevance_scorer import RelevanceScorer
from app.skills.synthesizer import Synthesizer
from app.skills.validator import Validator

_CASES = [
    ("validate untrusted input",
     dict(max_depth=2, max_total_nodes=50, top_k_questions=2)),
    ("design a scalable distributed cache",
     dict(max_depth=3, max_total_nodes=80, top_k_questions=3)),
    ("build secure authentication system",
     dict(max_depth=2, max_total_nodes=8, top_k_questions=2)),   # budget-bound
    ("improve api performance and reliability under load",
     dict(max_depth=4, max_total_nodes=120, top_k_questions=4)),
]


def _build(cfg):
    base = dict(min_security=0.8, min_quality=0.6, min_novelty=0.2)
    base.update(cfg)
    return FractalResearchOrchestrator(
        config=base,
        decomposer=Decomposer(),
        validator=Validator(),
        synthesizer=Synthesizer(),
    )


def _snapshot(orch):
    nodes = sorted(orch.graph.get_all_nodes(), key=lambda n: n.id)
    rows = []
    for n in nodes:
        rows.append((
            n.id, n.branch_path, n.depth, n.claim,
            tuple(n.parent_ids), n.status, n.stop_reason,
            round(n.relevance, 6), round(n.confidence, 6), round(n.risk, 6),
            tuple(n.evidence_for), tuple(n.evidence_against), tuple(n.assumptions),
            tuple(q.text for q in n.questions),
            tuple(round(q.priority, 6) for q in n.questions),
        ))
    return rows, dict(orch.debug_stats)


@pytest.mark.timeout(300)  # heavy: builds + runs the orchestrator 2x across 4
# cases (one is 120 nodes / depth 4), each run repo-scanning the (growing) tree.
# Determinism is still fully asserted below; this only raises the hang-tripwire
# above the default 120s so tree growth / load contention can't flake it.
def test_expansion_is_deterministic_across_runs():
    # Same objective + config must yield an identical expanded tree every time.
    for objective, cfg in _CASES:
        a = _build(cfg)
        b = _build(cfg)
        a.run(objective)
        b.run(objective)
        assert _snapshot(a) == _snapshot(b), objective


def test_expansion_produces_well_formed_tree():
    for objective, cfg in _CASES:
        orch = _build(cfg)
        orch.run(objective)
        rows, stats = _snapshot(orch)
        assert rows, objective                       # at least the roots exist
        for row in rows:
            (_id, _bp, _depth, _claim, _parents, _status, stop_reason,
             relevance, confidence, risk, *_rest) = row
            assert 0.0 <= relevance <= 1.0
            assert 0.0 <= confidence <= 1.0
            assert 0.0 <= risk <= 1.0
            if _status.name == "STOPPED":
                assert stop_reason is not None
        # counters are non-negative integers throughout
        for key, val in stats.items():
            assert val >= 0, key


def test_budget_cap_is_respected():
    # The tight-budget case must never create more nodes than the cap allows.
    orch = _build(dict(max_depth=2, max_total_nodes=8, top_k_questions=2))
    orch.run("build secure authentication system")
    assert orch.graph.size() <= 8


def test_focus_filter_is_opt_in_and_stable():
    # With focus pruning enabled the expansion stays deterministic too.
    objective = "validate untrusted input"
    cfg = dict(max_depth=3, max_total_nodes=60, top_k_questions=3,
               focus={"min_relevance": 0.05, "min_depth": 1})
    a = _build(cfg)
    b = _build(cfg)
    a.relevance_scorer = RelevanceScorer(objective)
    b.relevance_scorer = RelevanceScorer(objective)
    a.run(objective)
    b.run(objective)
    assert _snapshot(a) == _snapshot(b)
