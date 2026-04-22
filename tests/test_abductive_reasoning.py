from __future__ import annotations

from app.engine.abductive_reasoning import AbductiveReasoner, AbductionResult


def test_abduction_long_function():
    reasoner = AbductiveReasoner()
    observation = {"type": "long_function", "line_count": 55, "function_name": "process"}
    result = reasoner.infer([observation])
    assert len(result.root_causes) >= 1
    assert any("multiple" in rc.lower() or "responsibilit" in rc.lower() for rc in result.root_causes)


def test_abduction_many_arguments():
    reasoner = AbductiveReasoner()
    observation = {"type": "many_arguments", "arg_count": 7, "function_name": "create"}
    result = reasoner.infer([observation])
    assert any("parameter object" in rc.lower() or "data class" in rc.lower() for rc in result.root_causes)


def test_abduction_high_import_count():
    reasoner = AbductiveReasoner()
    observation = {"type": "high_import_count", "import_count": 25, "file": "app/main.py"}
    result = reasoner.infer([observation])
    assert any("god" in rc.lower() or "cohesion" in rc.lower() for rc in result.root_causes)


def test_abduction_bare_except():
    reasoner = AbductiveReasoner()
    observation = {"type": "bare_except", "function_name": "handler"}
    result = reasoner.infer([observation])
    assert any("specific" in rc.lower() or "error handling" in rc.lower() for rc in result.root_causes)


def test_abduction_multiple_observations():
    reasoner = AbductiveReasoner()
    observations = [
        {"type": "long_function", "line_count": 60},
        {"type": "many_arguments", "arg_count": 8},
        {"type": "missing_docstring"},
    ]
    result = reasoner.infer(observations)
    assert result.confidence > 0.5
    assert len(result.root_causes) >= 2


def test_abduction_result_to_dict():
    reasoner = AbductiveReasoner()
    result = reasoner.infer([{"type": "missing_docstring"}])
    d = result.to_dict()
    assert "root_causes" in d
    assert "confidence" in d
