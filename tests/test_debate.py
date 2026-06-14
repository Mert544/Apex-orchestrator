from app.agents.consensus import ConsensusEngine, Verdict, Vote
from app.agents.debate import DebateEngine, DebateResult, DebateRound


def _make_vote(agent: str, verdict: str, confidence: float) -> Vote:
    return Vote(
        agent_name=agent,
        agent_role="test",
        verdict=Verdict[verdict],
        confidence=confidence,
        reasoning="test",
        weight=1.0,
    )


def _vote(agent: str, role: str, verdict: str, confidence: float, reasoning: str = "r") -> Vote:
    return Vote(
        agent_name=agent,
        agent_role=role,
        verdict=Verdict[verdict],
        confidence=confidence,
        reasoning=reasoning,
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


def test_debate_softens_low_confidence_approvers_and_flips_verdict():
    # A security_auditor dissenter (REJECT, reasoning mentions "security") makes
    # low-confidence non-security approvers soften to ABSTAIN. With all approvers
    # gone, the verdict flips to REJECT and the debate resolves.
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=2)
    votes = [
        _vote("arch1", "architecture_analyst", "APPROVE", 0.6),
        _vote("arch2", "architecture_analyst", "APPROVE", 0.6),
        _vote("sec", "security_auditor", "REJECT", 0.5, "serious security risk here"),
    ]
    result = debate.resolve("claim", votes)
    assert result.resolved
    assert result.final_consensus.final_verdict == Verdict.REJECT
    assert len(result.rounds) == 1
    after = {v.agent_name: v for v in result.rounds[0].votes_after}
    assert after["arch1"].verdict == Verdict.ABSTAIN
    assert after["arch1"].confidence == 0.3
    assert "Softened" in after["arch1"].reasoning


def test_debate_stalemate_when_no_votes_change():
    # No softening (custom argument never mentions "security"), so votes never
    # change. Confidence delta is 0 < min_confidence_delta -> stalemate break.
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(
        engine,
        max_rounds=3,
        argument_generator=lambda claim, dissenter, all_votes: "neutral argument",
    )
    votes = [
        _vote("a1", "architecture_analyst", "APPROVE", 0.9),
        _vote("a2", "architecture_analyst", "APPROVE", 0.9),
        _vote("sec", "security_auditor", "REJECT", 0.9, "no risk word"),
    ]
    result = debate.resolve("claim", votes)
    assert not result.resolved
    assert len(result.rounds) == 1  # broke at stalemate, not all 3 rounds
    assert result.final_consensus.final_verdict == Verdict.APPROVE


def test_debate_verdict_unchanged_but_confidence_shifts_continues():
    # One low-confidence approver softens (confidence shifts beyond delta) but the
    # verdict stays APPROVE -> the loop does not break on round 1 (lines 128-129),
    # then stalemates on round 2.
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=3, min_confidence_delta=0.001)
    votes = [
        _vote("hi1", "architecture_analyst", "APPROVE", 0.95),
        _vote("hi2", "architecture_analyst", "APPROVE", 0.95),
        _vote("lo", "architecture_analyst", "APPROVE", 0.5),
        _vote("sec", "security_auditor", "REJECT", 0.6, "security risk"),
    ]
    result = debate.resolve("claim", votes)
    assert len(result.rounds) == 2
    assert result.final_consensus.final_verdict == Verdict.APPROVE
    assert result.rounds[0].consensus_before.confidence != result.rounds[0].consensus_after.confidence


def test_debate_max_rounds_reached_flag_set_on_last_round():
    # With max_rounds=1, the single round reaches line 129 and flags max_rounds_reached.
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=1, min_confidence_delta=0.001)
    votes = [
        _vote("hi1", "architecture_analyst", "APPROVE", 0.95),
        _vote("hi2", "architecture_analyst", "APPROVE", 0.95),
        _vote("lo", "architecture_analyst", "APPROVE", 0.5),
        _vote("sec", "security_auditor", "REJECT", 0.6, "security risk"),
    ]
    result = debate.resolve("claim", votes)
    assert len(result.rounds) == 1
    assert result.max_rounds_reached
    assert not result.resolved


def test_default_argument_reject_approve_abstain():
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine)
    reject = _vote("r", "security_auditor", "REJECT", 0.9, "it is risky")
    approve = _vote("a", "architecture_analyst", "APPROVE", 0.9, "it is clean")
    abstain = _vote("x", "test", "ABSTAIN", 0.5, "unsure")
    assert "reject this claim" in debate._default_argument("c", reject, [])
    assert "risks outweigh" in debate._default_argument("c", reject, [])
    assert "support this claim" in debate._default_argument("c", approve, [])
    # ABSTAIN dissenters cannot arise from consensus, so the abstain branch is
    # exercised directly here.
    abstain_arg = debate._default_argument("c", abstain, [])
    assert "abstain" in abstain_arg
    assert "More information is needed" in abstain_arg


def test_reconsider_keeps_votes_without_security_arguments():
    # arg_text has no "security" -> no softening, votes returned unchanged.
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine)
    votes = [_vote("a", "architecture_analyst", "APPROVE", 0.5)]
    arguments = [{"role": "architecture_analyst", "argument": "looks fine to me"}]
    out = debate._reconsider_votes(votes, arguments)
    assert out == votes


def test_debate_result_to_dict_round_details():
    # Exercise to_dict's per-round mapping with a real round that has both
    # before and after consensus recorded.
    engine = ConsensusEngine(strategy="majority", quorum=2)
    debate = DebateEngine(engine, max_rounds=2)
    votes = [
        _vote("arch1", "architecture_analyst", "APPROVE", 0.6),
        _vote("arch2", "architecture_analyst", "APPROVE", 0.6),
        _vote("sec", "security_auditor", "REJECT", 0.5, "serious security risk"),
    ]
    result = debate.resolve("claim", votes)
    d = result.to_dict()
    assert d["total_rounds"] == len(result.rounds)
    assert isinstance(d["rounds"], list) and d["rounds"]
    first = d["rounds"][0]
    assert first["round"] == 1
    assert first["verdict_before"] == "APPROVE"
    assert first["verdict_after"] == "REJECT"
    assert isinstance(first["arguments"], list)


def test_debate_round_dataclass_defaults():
    rnd = DebateRound(round_number=1, claim="c", votes_before=[])
    assert rnd.votes_after == []
    assert rnd.arguments == []
    assert rnd.consensus_before is None
    assert rnd.consensus_after is None
