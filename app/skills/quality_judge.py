class QualityJudge:
    def evaluate(self, node) -> float:
        score = 0.35
        if node.evidence_for:
            score += 0.20
        if node.evidence_against:
            score += 0.15
        if node.assumptions:
            score += 0.10
        if len(node.questions) >= 4:
            score += 0.10
        return min(score, 1.0)
