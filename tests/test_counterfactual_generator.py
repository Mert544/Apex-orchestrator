from __future__ import annotations

from app.engine.counterfactual_generator import CounterfactualGenerator, CounterfactualResult


def test_generates_counterfactual_for_missing_guard():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Function process lacks input validation",
        "context": "def process(data):\n    return eval(data)",
    }
    result = gen.generate(claim)
    assert len(result.scenarios) > 0
    assert any("if" in s.lower() or "without" in s.lower() for s in result.scenarios)


def test_generates_counterfactual_for_eval():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Function parse uses eval()",
        "context": "def parse(expr):\n    return eval(expr)",
    }
    result = gen.generate(claim)
    assert any("expression" in s.lower() or "trusted" in s.lower() for s in result.scenarios)


def test_generates_counterfactual_for_missing_docstring():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Function helper has no docstring",
        "context": "def helper(x):\n    return x * 2",
    }
    result = gen.generate(claim)
    assert len(result.scenarios) >= 1


def test_generates_what_if_scenarios():
    gen = CounterfactualGenerator()
    claim = {
        "text": "No error handling in network call",
        "context": "def fetch(url):\n    return requests.get(url).json()",
    }
    result = gen.generate(claim)
    assert any("timeout" in s.lower() or "disconnect" in s.lower() or "unavailable" in s.lower() for s in result.scenarios)


def test_result_to_dict():
    gen = CounterfactualGenerator()
    result = gen.generate({"text": "Test claim", "context": ""})
    d = result.to_dict()
    assert "scenarios" in d
    assert "insight" in d


def test_insight_generated():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Database password is hardcoded",
        "context": "DB_PASSWORD = 'secret123'",
    }
    result = gen.generate(claim)
    assert result.insight != ""
    assert len(result.scenarios) >= 2
