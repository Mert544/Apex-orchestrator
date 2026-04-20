def score_confidence(evidence_for_count: int, evidence_against_count: int) -> float:
    if evidence_for_count == 0:
        return 0.25
    if evidence_against_count >= evidence_for_count:
        return 0.45
    if evidence_for_count >= 3 and evidence_against_count == 0:
        return 0.85
    return 0.65


def score_question_priority(impact: float, uncertainty: float, risk: float, novelty: float) -> float:
    return 0.35 * impact + 0.25 * uncertainty + 0.20 * risk + 0.20 * novelty


def score_claim_priority(impact: float, risk: float, novelty: float, evidence_gap: float) -> float:
    return 0.35 * impact + 0.30 * risk + 0.20 * novelty + 0.15 * evidence_gap
