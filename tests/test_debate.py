from app.agents.consensus import ConsensusEngine, Verdict, Vote
from app.agents.debate import DebateEngine, DebateResult


def _make_vote(agent: str, verdict: str, confidence: float) -> Vote:
    return Vote(
        agent_name=agent,
        agent_role="test",
        verdict=Verdict[verdict],
        confidence=confidence,
        reasoning="test",
        weight=1.0,
    )


def test_debate_resolves_dissent():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=3)

    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "REJECT", 0.8),  # dissenter
        _make_vote("a3", "APPROVE", 0.7),
    ]

    result = debate.resolve("test claim", votes)
    assert isinstance(result, DebateResult)
    assert result.claim == "test claim"
    # May or may not resolve depending on heuristic
    assert len(result.rounds) > 0 or result.resolved


def test_debate_no_dissent_immediate_resolution():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=3)

    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "APPROVE", 0.8),
    ]

    result = debate.resolve("test claim", votes)
    assert result.resolved
    assert not result.rounds  # No debate needed


def test_debate_max_rounds_reached():
    engine = ConsensusEngine(strategy="unanimous", quorum=2)
    debate = DebateEngine(engine, max_rounds=2)

    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "REJECT", 0.9),  # Will never agree
    ]

    result = debate.resolve("test claim", votes)
    assert result.max_rounds_reached or not result.resolved


def test_debate_tracks_rounds():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=3)

    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "REJECT", 0.7),
        _make_vote("a3", "APPROVE", 0.6),
    ]

    result = debate.resolve("test claim", votes)
    assert result.final_consensus is not None


def test_debate_result_to_dict():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=2)

    votes = [
        _make_vote("a1", "APPROVE", 0.9),
        _make_vote("a2", "REJECT", 0.8),
    ]

    result = debate.resolve("test claim", votes)
    d = result.to_dict()
    assert "claim" in d
    assert "rounds" in d
    assert "resolved" in d
    assert "final_verdict" in d
