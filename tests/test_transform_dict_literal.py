from __future__ import annotations

import ast

from app.execution.semantic.transforms import dict_literal


def _new_content(source: str) -> str | None:
    result = dict_literal.apply("mod.py", source, "title")
    if result is None:
        return None
    return result.patch_requests[0]["new_content"]


def test_basic_rewrite() -> None:
    assert _new_content("dict(a=1, b=2)\n") == '{"a": 1, "b": 2}\n'


def test_value_text_preserved_with_call() -> None:
    assert _new_content("dict(x=foo())\n") == '{"x": foo()}\n'


def test_order_preserved() -> None:
    out = _new_content("dict(b=2, a=1)\n")
    assert out == '{"b": 2, "a": 1}\n'


def test_single_kwarg() -> None:
    assert _new_content("dict(only=True)\n") == '{"only": True}\n'


def test_refuse_empty() -> None:
    assert _new_content("dict()\n") is None


def test_refuse_kwargs_unpacking() -> None:
    assert _new_content("dict(**o)\n") is None


def test_refuse_mixed_unpacking() -> None:
    assert _new_content("dict(a=1, **o)\n") is None


def test_refuse_positional() -> None:
    assert _new_content("dict(o, a=1)\n") is None


def test_refuse_positional_list_of_pairs() -> None:
    assert _new_content('dict([("a", 1)])\n') is None


def test_refuse_star_args() -> None:
    assert _new_content("dict(*pairs)\n") is None


def test_not_builtin_attribute() -> None:
    # collections.dict(a=1) — callee is not the bare Name `dict`
    assert _new_content("mod.dict(a=1)\n") is None


def test_no_op_returns_none() -> None:
    assert _new_content("x = 1\n") is None


def test_syntax_error_returns_none() -> None:
    assert _new_content("def (:\n") is None


def test_preserves_trailing_newline_absence() -> None:
    out = _new_content("dict(a=1)")
    assert out == '{"a": 1}'


def test_nested_value_expression() -> None:
    out = _new_content("dict(k=a + b * c)\n")
    assert out == '{"k": a + b * c}\n'


def test_assignment_context() -> None:
    out = _new_content("result = dict(name=value, count=n)\n")
    assert out == 'result = {"name": value, "count": n}\n'


def test_multiple_calls_rewritten() -> None:
    out = _new_content("x = dict(a=1)\ny = dict(b=2)\n")
    assert out == 'x = {"a": 1}\ny = {"b": 2}\n'


def test_determinism() -> None:
    source = "dict(a=foo(), b=g(1, 2), c=x)\n"
    first = _new_content(source)
    second = _new_content(source)
    assert first == second
    assert first is not None


def test_output_always_parseable() -> None:
    sources = [
        "dict(a=1, b=2)\n",
        "dict(x=foo())\n",
        "result = dict(name=value, count=n)\n",
        "dict(k={'nested': 1})\n",
        "x = dict(a=1)\ny = dict(b=2)\n",
    ]
    for source in sources:
        out = _new_content(source)
        assert out is not None
        ast.parse(out)


def test_semantic_equality() -> None:
    # Evaluate both the original dict() call and the rewritten literal and
    # confirm they produce equal dicts.
    foo = 7  # noqa: F841 (referenced via eval namespace)
    source = "dict(a=1, b=foo, c=foo + 1)"
    out = _new_content(source + "\n")
    assert out is not None
    namespace = {"foo": 7}
    original = eval(source, dict(namespace))  # noqa: S307
    rewritten = eval(out.strip(), dict(namespace))  # noqa: S307
    assert original == rewritten
    assert original == {"a": 1, "b": 7, "c": 8}


def test_semantic_equality_with_call_value() -> None:
    source = "dict(x=str(1), y=len([1, 2, 3]))"
    out = _new_content(source + "\n")
    assert out is not None
    assert eval(source) == eval(out.strip())  # noqa: S307
