from __future__ import annotations

import ast

from app.execution.semantic.transforms import tuple_membership


def _apply(source: str):
    return tuple_membership.apply("mod.py", source, "title")


def _new_content(source: str) -> str | None:
    result = _apply(source)
    if result is None:
        return None
    return result.patch_requests[0]["new_content"]


def test_two_way_string_membership():
    src = 'x = s == "a" or s == "b"\n'
    out = _new_content(src)
    assert out is not None
    assert 's in (\'a\', \'b\')' in out or 's in ("a", "b")' in out


def test_three_way_membership():
    src = "x = s == a or s == b or s == c\n"
    out = _new_content(src)
    assert out is not None
    assert "s in (a, b, c)" in out


def test_attribute_left_and_right():
    src = "x = obj.kind == m.A or obj.kind == m.B\n"
    out = _new_content(src)
    assert out is not None
    assert "obj.kind in (m.A, m.B)" in out


def test_right_side_order_preserved():
    src = "x = v == 3 or v == 1 or v == 2\n"
    out = _new_content(src)
    assert out is not None
    assert "v in (3, 1, 2)" in out


def test_refuse_different_left():
    assert _apply("x = a == 1 or y == 2\n") is None


def test_refuse_side_effectful_operand():
    assert _apply("x = f() == a or f() == b\n") is None


def test_refuse_subscript_left():
    assert _apply("x = d[0] == a or d[0] == b\n") is None


def test_refuse_call_on_right():
    assert _apply("x = v == f() or v == g()\n") is None


def test_refuse_mixed_ops():
    assert _apply("x = v == a or v < b\n") is None


def test_refuse_not_equal():
    assert _apply("x = v != a or v != b\n") is None


def test_refuse_single_compare():
    assert _apply("x = v == a\n") is None


def test_refuse_non_comparison_or_term():
    assert _apply("x = v == a or flag\n") is None


def test_refuse_unrelated_bool_term():
    assert _apply("x = v == a or other == b or unrelated()\n") is None


def test_no_op_returns_none():
    assert _apply("x = v == a and v == b\n") is None


def test_syntax_error_returns_none():
    assert _apply("def broken(:\n") is None


def test_determinism():
    src = "x = s == a or s == b or s == c\n"
    first = _new_content(src)
    second = _new_content(src)
    assert first == second


def test_never_unparseable():
    src = "x = s == 1 or s == 2 or s == 3\n"
    out = _new_content(src)
    assert out is not None
    ast.parse(out)


def test_semantic_equality_for_normal_eq():
    out = _new_content("y = s == 1 or s == 2\n")
    assert out is not None
    for s in (0, 1, 2, 3):
        ns_old: dict = {"s": s}
        ns_new: dict = {"s": s}
        exec("y = s == 1 or s == 2", ns_old)
        exec(out, ns_new)
        assert ns_old["y"] == ns_new["y"]


def test_idempotent_already_membership():
    assert _apply("x = s in (1, 2)\n") is None
