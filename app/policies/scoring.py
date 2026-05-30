def score_confidence(evidence_for_count: int, evidence_against_count: int) -> float:
    if evidence_for_count == 0:
        return 0.25
    if evidence_against_count >= evidence_for_count:
        return 0.45
    if evidence_for_count >= 3 and evidence_against_count == 0:
        return 0.85
    return 0.65


def _focus_multiplier(relevance: float) -> float:
    """Map relevance-to-objective into a [0.5, 1.0] priority multiplier.

    relevance == 1.0 -> 1.0 (no change; the backward-compatible default).
    relevance == 0.0 -> 0.5 (off-topic branches are halved, not erased), so
    the tree stays focused on the main idea without ignoring weak signals.
    """
    return 0.5 + 0.5 * max(0.0, min(1.0, relevance))


def score_question_priority(
    impact: float, uncertainty: float, risk: float, novelty: float, relevance: float = 1.0
) -> float:
    base = 0.35 * impact + 0.25 * uncertainty + 0.20 * risk + 0.20 * novelty
    return base * _focus_multiplier(relevance)


def score_claim_priority(
    impact: float, risk: float, novelty: float, evidence_gap: float, relevance: float = 1.0
) -> float:
    base = 0.35 * impact + 0.30 * risk + 0.20 * novelty + 0.15 * evidence_gap
    return base * _focus_multiplier(relevance)
