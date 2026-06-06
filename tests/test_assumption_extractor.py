from app.skills.assumption_extractor import AssumptionExtractor


def test_extract_returns_two_assumptions_embedding_the_claim():
    claim = "the model is fair"
    out = AssumptionExtractor().extract(claim)
    assert len(out) == 2
    assert all(claim in line for line in out)


def test_extract_covers_representativeness_and_relevance():
    out = AssumptionExtractor().extract("X")
    joined = " ".join(out).lower()
    assert "representative" in joined
    assert "relevant" in joined


def test_extract_is_deterministic():
    e = AssumptionExtractor()
    assert e.extract("same") == e.extract("same")


def test_extract_handles_empty_claim():
    out = AssumptionExtractor().extract("")
    assert len(out) == 2
    assert all(isinstance(line, str) and line for line in out)
