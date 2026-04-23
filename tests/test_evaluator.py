from app.agents.evaluator import ClaimEvaluator


def test_evaluator_security_risk_rejected():
    evaluator = ClaimEvaluator()
    result = evaluator.evaluate("Use eval() for dynamic configuration loading")

    assert result.final_verdict.name == "REJECT"
    assert any(v.agent_role == "security_auditor" and v.verdict.name == "REJECT" for v in result.votes)


def test_evaluator_docstring_claim_approved():
    evaluator = ClaimEvaluator()
    result = evaluator.evaluate("Add docstrings to all public functions")

    assert result.final_verdict.name == "APPROVE"
    assert any(v.agent_role == "documentation_enforcer" and v.verdict.name == "APPROVE" for v in result.votes)


def test_evaluator_architecture_claim_approved():
    evaluator = ClaimEvaluator()
    result = evaluator.evaluate("Reduce dependency coupling in auth module")

    assert result.final_verdict.name == "APPROVE"
    assert any(v.agent_role == "architecture_analyst" and v.verdict.name == "APPROVE" for v in result.votes)


def test_evaluator_test_claim_approved():
    evaluator = ClaimEvaluator()
    result = evaluator.evaluate("Add test coverage for checkout flow")

    assert result.final_verdict.name == "APPROVE"
    assert any(v.agent_role == "test_coverage_analyst" and v.verdict.name == "APPROVE" for v in result.votes)


def test_evaluator_batch_processing():
    evaluator = ClaimEvaluator()
    claims = [
        "Add docstrings",
        "Use eval() for configuration",
        "Reduce coupling",
    ]
    results = evaluator.evaluate_batch(claims)
    assert len(results) == 3


def test_evaluator_filter_approved():
    evaluator = ClaimEvaluator()
    claims = [
        "Add docstrings",
        "Use eval() for configuration",
        "Add test coverage",
    ]
    approved = evaluator.filter_approved(claims, min_confidence=0.5)
    # eval claim should be rejected
    assert len(approved) == 2
    assert all(r.final_verdict.name == "APPROVE" for _, r in approved)


def test_evaluator_panel_info():
    evaluator = ClaimEvaluator()
    info = evaluator.to_dict()
    assert info["panel_size"] == 4
    assert "security" in info["agents"]
