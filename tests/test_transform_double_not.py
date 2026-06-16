import ast

from app.execution.semantic.transforms import double_not


def _apply(source: str):
    return double_not.apply("mod.py", source, "simplify double negation")


def _new_content(source: str) -> str:
    result = _apply(source)
    assert result is not None
    return result.patch_requests[0]["new_content"]


# --- rewrites -------------------------------------------------------------


def test_assignment_value_context():
    out = _new_content("y = not not x\n")
    assert out == "y = bool(x)\n"


def test_if_condition():
    out = _new_content("if not not flag:\n    pass\n")
    assert out == "if bool(flag):\n    pass\n"


def test_attribute_operand():
    out = _new_content("y = not not obj.ready\n")
    assert out == "y = bool(obj.ready)\n"


def test_constant_operand():
    out = _new_content("y = not not 0\n")
    assert out == "y = bool(0)\n"


def test_compare_operand():
    out = _new_content("y = not not (a == b)\n")
    assert out == "y = bool(a == b)\n"


def test_result_metadata():
    result = _apply("y = not not x\n")
    assert result is not None
    assert result.transform_type == "double_not_to_bool"
    assert result.patch_requests[0]["expected_old_content"] == "y = not not x\n"
    assert result.patch_requests[0]["path"] == "mod.py"


# --- refusals -------------------------------------------------------------


def test_single_not_refused():
    assert _apply("y = not x\n") is None


def test_triple_not_refused():
    assert _apply("y = not not not x\n") is None


def test_not_of_boolop_refused():
    # `not (not a and b)` -- inner is a BoolOp, not a plain `not`.
    assert _apply("y = not (not a and b)\n") is None


def test_not_of_call_operand_refused():
    # Call has potential side effects, so it is not in the safe operand set.
    assert _apply("y = not not f()\n") is None


def test_no_double_not_returns_none():
    assert _apply("y = x and z\n") is None


def test_syntax_error_returns_none():
    assert _apply("def broken(:\n") is None


# --- robustness -----------------------------------------------------------


def test_determinism():
    src = "y = not not x\n"
    first = _apply(src)
    second = _apply(src)
    assert first is not None and second is not None
    assert first.patch_requests[0]["new_content"] == second.patch_requests[0]["new_content"]


def test_output_always_parses():
    for src in (
        "y = not not x\n",
        "if not not flag:\n    pass\n",
        "y = not not obj.ready\n",
        "y = not not (a == b)\n",
        "z = [not not v]\n",
    ):
        result = _apply(src)
        if result is None:
            continue
        ast.parse(result.patch_requests[0]["new_content"])


def test_only_target_span_changed():
    src = "before = 1\ny = not not x\nafter = 2\n"
    out = _new_content(src)
    assert "before = 1\n" in out
    assert "after = 2\n" in out
    assert "y = bool(x)\n" in out


def test_semantic_equality_across_truthy_falsy():
    # `not not x` must equal `bool(x)` for representative truthy/falsy values.
    for value in (0, 1, -1, "", "a", [], [1], None, 0.0, 3.14, {}, {"k": 1}):
        env = {"x": value}
        original = eval("not not x", env)
        rewritten = eval("bool(x)", env)
        assert original == rewritten
        assert isinstance(rewritten, bool)
