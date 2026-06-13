from __future__ import annotations

import ast

from app.engine.detectors import detect, has_collection_literal
from app.execution.semantic.transforms import collection_literal as cl


def _apply(src: str) -> str | None:
    r = cl.apply("m.py", src, "modernize collection literal")
    return r.patch_requests[0]["new_content"] if r else None


def test_empty_dict_list_tuple_become_literals():
    out = _apply("a = dict()\nb = list()\nc = tuple()\n")
    assert out == "a = {}\nb = []\nc = ()\n"
    ast.parse(out)


def test_constructor_with_args_untouched():
    # Real arguments carry semantics — never rewritten.
    assert _apply("a = dict(x=1)\n") is None
    assert _apply("a = list(range(3))\n") is None
    assert _apply("a = tuple(items)\n") is None


def test_set_not_rewritten():
    # set() has no empty literal ({} is a dict) — must be left alone.
    assert _apply("s = set()\n") is None


def test_existing_literal_untouched():
    assert _apply("d = {1: 2}\nl = [1]\n") is None


def test_call_in_expression_position():
    out = _apply("def f():\n    return dict()\n")
    assert out is not None and "return {}" in out
    ast.parse(out)


def test_nested_and_multiple_on_one_line():
    out = _apply("x = (dict(), list())\n")
    assert out == "x = ({}, [])\n"
    ast.parse(out)


def test_multiline_call_skipped():
    # A call spanning lines is skipped to keep the splice exact.
    assert _apply("x = dict(\n)\n") is None


def test_detector_flags_only_zero_arg_constructors():
    src = "a = dict()\nb = dict(x=1)\nc = list()\nd = list(y)\ne = set()\n"
    lines = sorted(i.line for i in detect(src) if i.fix_kind == "collection-literal")
    assert lines == [1, 3]


def test_detector_message_names_the_literal():
    msgs = {i.message for i in detect("a = tuple()\n") if i.fix_kind == "collection-literal"}
    assert any("`()`" in m and "tuple()" in m for m in msgs)


def test_detector_and_transform_idempotent():
    src = "def f():\n    return list()\n"
    assert has_collection_literal(src)
    once = _apply(src)
    assert once is not None and "list()" not in once
    assert _apply(once) is None


def test_noqa_c408_suppresses():
    src = "a = dict()  # noqa: C408\n"
    assert not any(i.fix_kind == "collection-literal" for i in detect(src))


def test_value_equivalence():
    # Property: every rewrite preserves the runtime value.
    for expr in ("dict()", "list()", "tuple()"):
        out = _apply(f"v = {expr}\n")
        assert out is not None
        new_expr = out.split("=", 1)[1].strip()
        assert eval(expr) == eval(new_expr)
