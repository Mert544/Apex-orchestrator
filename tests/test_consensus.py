from app.agents.consensus import ConsensusEngine, ConsensusResult, Verdict, Vote


def _make_vote(agent: str, verdict: str, confidence: float, weight: float = 1.0) -> Vote:
    return Vote(
        agent_name=agent,
        agent_role="test",
        verdict=Verdict[verdict],
        confidence=confidence,
        reasoning="test",
        weight=weight,
    )


def test_unanimous_all_approve():
    engine = ConsensusEngine(strategy="unanimous", quorum=2)
    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "APPROVE", 0.8),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.APPROVE
    assert result.confidence == 0.8  # min confidence
    assert result.quorum_reached


def test_unanimous_one_rejects():
    engine = ConsensusEngine(strategy="unanimous", quorum=2)
    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "REJECT", 0.7),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.REJECT


def test_majority_approve():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    votes = [
        _make_vote("a1", "APPROVE", 0.9, weight=1.0),
        _make_vote("a2", "APPROVE", 0.8, weight=1.0),
        _make_vote("a3", "REJECT", 0.6, weight=1.0),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.APPROVE
    assert result.confidence > 0.8


def test_majority_reject():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    votes = [
        _make_vote("a1", "APPROVE", 0.9, weight=1.0),
        _make_vote("a2", "REJECT", 0.8, weight=2.0),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.REJECT


def test_supermajority_not_enough():
    engine = ConsensusEngine(strategy="supermajority", quorum=2)
    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "REJECT", 0.9),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.ABSTAIN


def test_weighted_positive():
    engine = ConsensusEngine(strategy="weighted", quorum=2)
    votes = [
        _make_vote("a1", "APPROVE", 0.9, weight=2.0),
        _make_vote("a2", "REJECT", 0.5, weight=1.0),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.APPROVE


def test_threshold_hit():
    engine = ConsensusEngine(strategy="threshold", quorum=1, min_confidence=0.8)
    votes = [
        _make_vote("a1", "APPROVE", 0.9),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.APPROVE


def test_quorum_not_met():
    engine = ConsensusEngine(strategy="majority", quorum=5)
    votes = [
        _make_vote("a1", "APPROVE", 0.9),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.ABSTAIN
    assert not result.quorum_reached


def test_dissent_tracking():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "REJECT", 0.8),
        _make_vote("a3", "APPROVE", 0.7),
    ]
    result = engine.evaluate("test claim", votes)
    assert result.final_verdict == Verdict.APPROVE
    assert len(result.dissent) == 1
    assert result.dissent[0].agent_name == "a2"


def test_consensus_result_to_dict():
    engine = ConsensusEngine(strategy="majority", quorum=1)
    votes = [_make_vote("a1", "APPROVE", 0.9)]
    result = engine.evaluate("claim", votes)
    d = result.to_dict()
    assert d["claim"] == "claim"
    assert d["verdict"] == "APPROVE"
    assert "votes" in d
    assert "dissent" in d
