from app.skills.claim_normalizer import ClaimNormalizer


def test_claim_normalizer_converts_question_to_missing_information_claim():
    normalizer = ClaimNormalizer()
    text = (
        "What critical information is missing to validate this claim: "
        "Dependency hub claim: the files app/services/order_service.py, app/payments/gateway.py, "
        "appear central in the import graph and should be expanded first for dependency risk and architectural coupling?"
    )

    normalized = normalizer.normalize(text)

    assert normalized is not None
    assert normalized.startswith("Missing-information claim:")
    assert "app/services/order_service.py" in normalized
    assert "app/payments/gateway.py" in normalized
    assert "What critical information" not in normalized


def test_claim_normalizer_rejects_tiny_or_fragmented_claims():
    normalizer = ClaimNormalizer()

    assert normalizer.is_viable("py") is False
    assert normalizer.is_viable("What critical information is missing?") is False
    assert normalizer.is_viable("Dependency hub claim: app/services/order_service.py should be inspected for architectural coupling.") is True
