from __future__ import annotations

from app.engine.hypothesis_mapper import HypothesisMapper, HypothesisTestMapping


def test_maps_input_validation_claim():
    mapper = HypothesisMapper()
    claim = {
        "text": "Function process lacks input validation",
        "target_function": "process",
        "source_file": "app/main.py",
    }
    result = mapper.map_to_test(claim)
    assert result.hypothesis == "process raises ValueError on invalid input"
    assert any("pytest.raises(ValueError)" in t for t in result.test_snippets)
    assert result.is_testable is True


def test_maps_missing_docstring_claim():
    mapper = HypothesisMapper()
    claim = {
        "text": "Function helper has no docstring",
        "target_function": "helper",
        "source_file": "app/utils.py",
    }
    result = mapper.map_to_test(claim)
    assert result.hypothesis == "helper has a non-empty docstring"
    assert any("__doc__" in t for t in result.test_snippets)
    assert result.is_testable is True


def test_maps_eval_risk_claim():
    mapper = HypothesisMapper()
    claim = {
        "text": "Function parse uses eval() which is dangerous",
        "target_function": "parse",
        "source_file": "app/parser.py",
    }
    result = mapper.map_to_test(claim)
    assert "eval" in result.hypothesis.lower() or "ast.literal_eval" in result.hypothesis.lower()
    assert result.is_testable is True


def test_returns_none_for_vague_claim():
    mapper = HypothesisMapper()
    claim = {
        "text": "Code quality could be improved",
        "target_function": "",
        "source_file": "app/main.py",
    }
    result = mapper.map_to_test(claim)
    assert result.is_testable is False


def test_produces_test_file_path():
    mapper = HypothesisMapper()
    claim = {
        "text": "Function add has no type annotations",
        "target_function": "add",
        "source_file": "app/math.py",
    }
    result = mapper.map_to_test(claim)
    assert result.test_file_path == "tests/test_math.py"


def test_generates_full_test_snippet():
    mapper = HypothesisMapper()
    claim = {
        "text": "Function divide lacks zero-division guard",
        "target_function": "divide",
        "source_file": "app/calc.py",
    }
    result = mapper.map_to_test(claim)
    assert len(result.test_snippets) >= 1
    snippet = result.test_snippets[0]
    assert "def test_" in snippet
    assert "divide" in snippet
