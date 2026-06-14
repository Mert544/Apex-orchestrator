"""Transform impact: function-scoping edge cases (nested defs, methods, unparse failure)."""

from __future__ import annotations

import ast

import app.engine.transform_impact as ti
from app.engine.transform_impact import measure_impact


def _by_metric(deltas):
    return {d.metric: d for d in deltas}


def test_scope_resolves_class_method_by_dotted_name():
    # The ClassDef recursion branch: "C.m" must descend into the class body.
    before = (
        "class C:\n"
        "    def m(self, x):\n"
        "        if x:\n"
        "            if x > 0:\n"
        "                return x\n"
        "        return 0\n"
    )
    after = (
        "class C:\n"
        "    def m(self, x):\n"
        "        if not x:\n"
        "            return 0\n"
        "        if x <= 0:\n"
        "            return 0\n"
        "        return x\n"
    )
    deltas = measure_impact(before, after, function="C.m")
    by = _by_metric(deltas)
    assert by["max nesting"].before == 2
    assert by["max nesting"].after == 1


def test_scope_resolves_nested_inner_function():
    # The nested-FunctionDef recursion branch: "outer.inner" is found inside outer.
    before = (
        "def outer():\n"
        "    def inner(x):\n"
        "        if x:\n"
        "            if x > 1:\n"
        "                return x\n"
        "        return 0\n"
        "    return inner\n"
    )
    after = (
        "def outer():\n"
        "    def inner(x):\n"
        "        if not x:\n"
        "            return 0\n"
        "        return x\n"
        "    return inner\n"
    )
    deltas = measure_impact(before, after, function="outer.inner")
    by = _by_metric(deltas)
    # Only inner is compared; outer's wrapper does not add nesting depth.
    assert by["max nesting"].before == 2
    assert by["max nesting"].after == 1


def test_scope_unparseable_before_source_yields_no_deltas():
    # _scope_function returns None on SyntaxError -> measure_impact bails out.
    broken = "def m(:\n    return 1\n"
    good = "def m(self):\n    return 1\n"
    assert measure_impact(broken, good, function="m") == []
    assert measure_impact(good, broken, function="m") == []


def test_scope_unparse_failure_yields_no_deltas(monkeypatch):
    # When ast.unparse raises (the (AttributeError, ValueError) guard), the
    # function can't be isolated and no deltas are produced.
    def boom(_node):
        raise ValueError("cannot unparse")

    monkeypatch.setattr(ti.ast, "unparse", boom)
    src = "def m(self):\n    if self:\n        return 1\n    return 0\n"
    assert measure_impact(src, src, function="m") == []


def test_scope_function_helper_returns_none_on_syntax_error():
    assert ti._scope_function("def f(:\n    pass\n", "f") is None


def test_scope_class_method_helper_renders_just_the_method():
    src = "class C:\n    def m(self):\n        return 7\n"
    out = ti._scope_function(src, "C.m")
    assert out is not None
    assert "def m(self)" in out
    # The rendered method parses standalone.
    ast.parse(out)
