"""Cognitive complexity: charges what taxes a READER, not a path counter."""

from __future__ import annotations

import ast

from app.tools.cognitive_complexity import (
    cognitive_complexity,
    function_cognitive_complexities,
)


def _fn(source: str):
    return ast.parse(source).body[0]


def test_flat_sequence_costs_nothing():
    assert cognitive_complexity(_fn(
        "def f(x):\n    a = x + 1\n    b = a * 2\n    return b\n")) == 0


def test_nesting_is_charged_progressively():
    # if(+1) > for(+2: 1+nesting1) > if(+3: 1+nesting2) = 6
    src = (
        "def f(xs):\n"
        "    if xs:\n"
        "        for x in xs:\n"
        "            if x > 0:\n"
        "                return x\n"
        "    return 0\n"
    )
    assert cognitive_complexity(_fn(src)) == 6


def test_elif_and_else_cost_flat_one():
    src = (
        "def f(x):\n"
        "    if x > 10:\n"      # +1
        "        return 'big'\n"
        "    elif x > 5:\n"     # +1 flat
        "        return 'mid'\n"
        "    else:\n"           # +1 flat
        "        return 'small'\n"
    )
    assert cognitive_complexity(_fn(src)) == 3


def test_flat_dispatcher_beats_nested_loop():
    # The metric's whole point: a flat 4-way dispatch reads easier than
    # a 3-level nest, and the numbers must say so (cyclomatic ties them).
    flat = (
        "def f(x):\n"
        "    if x == 1:\n        return 'a'\n"
        "    elif x == 2:\n        return 'b'\n"
        "    elif x == 3:\n        return 'c'\n"
        "    elif x == 4:\n        return 'd'\n"
        "    return ''\n"
    )
    nested = (
        "def g(xs):\n"
        "    for x in xs:\n"
        "        if x:\n"
        "            while x > 0:\n"
        "                x -= 1\n"
        "    return xs\n"
    )
    assert cognitive_complexity(_fn(flat)) == 4    # 1 + 1 + 1 + 1
    assert cognitive_complexity(_fn(nested)) == 6  # 1 + 2 + 3


def test_boolean_sequences_and_recursion():
    src = (
        "def f(a, b, c, n):\n"
        "    if a and b and c:\n"   # if +1, one bool sequence +1
        "        return f(a, b, c, n - 1)\n"  # recursion +1
        "    return n\n"
    )
    assert cognitive_complexity(_fn(src)) == 3


def test_except_handlers_and_qualified_names():
    src = (
        "class Svc:\n"
        "    def run(self, x):\n"
        "        try:\n"
        "            return 1 / x\n"
        "        except ZeroDivisionError:\n"  # +1
        "            return 0\n"
    )
    rows = function_cognitive_complexities(src)
    assert rows == [("Svc.run", 2, 1)]


def test_unparsable_source_is_silent():
    assert function_cognitive_complexities("def broken(:\n") == []


def test_function_cognitive_complexities_for_path_matches_source_variant(tmp_path):
    from pathlib import Path
    from app.tools.cognitive_complexity import (
        function_cognitive_complexities,
        function_cognitive_complexities_for_path,
    )

    src = (
        "def f(x):\n"
        "    if x:\n"
        "        for i in x:\n"
        "            if i:\n"
        "                return i\n"
        "    return x and x\n\n\n"
        "class K:\n"
        "    def m(self, y):\n"
        "        return y if y else 0\n"
    )
    mod: Path = tmp_path / "cog.py"
    mod.write_text(src, encoding="utf-8")
    assert function_cognitive_complexities_for_path(mod) == function_cognitive_complexities(src)


def test_function_cognitive_complexities_for_path_empty_paths(tmp_path):
    from app.tools.cognitive_complexity import function_cognitive_complexities_for_path

    assert function_cognitive_complexities_for_path(tmp_path / "missing.py") == []
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    assert function_cognitive_complexities_for_path(bad) == []
