"""Tests for the remove-redundant-else develop transform."""

from __future__ import annotations

import ast

from app.execution.redundant_else import plan_remove_redundant_else


def _write(tmp_path, source: str, rel: str = "mod.py") -> str:
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return rel


def _result(tmp_path, source: str):
    rel = _write(tmp_path, source)
    return rel, plan_remove_redundant_else(tmp_path, rel)


def test_simple_return_else_flattened(tmp_path):
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    else:\n"
        "        x = 2\n"
        "        return x\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    x = 2\n"
        "    return x\n"
    )
    assert plan.edits_by_file[rel] == 1
    assert not plan.blockers


def test_raise_terminal(tmp_path):
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        raise ValueError\n"
        "    else:\n"
        "        y = 1\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "def f(c):\n"
        "    if c:\n"
        "        raise ValueError\n"
        "    y = 1\n"
    )


def test_break_terminal(tmp_path):
    src = (
        "def f(items):\n"
        "    for c in items:\n"
        "        if c:\n"
        "            break\n"
        "        else:\n"
        "            z = c\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "def f(items):\n"
        "    for c in items:\n"
        "        if c:\n"
        "            break\n"
        "        z = c\n"
    )


def test_continue_terminal(tmp_path):
    src = (
        "def f(items):\n"
        "    for c in items:\n"
        "        if c:\n"
        "            continue\n"
        "        else:\n"
        "            w = c\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "def f(items):\n"
        "    for c in items:\n"
        "        if c:\n"
        "            continue\n"
        "        w = c\n"
    )


def test_non_terminal_body_untouched(tmp_path):
    # The if body does NOT exit, so the else is not redundant — leave it.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        a = 1\n"
        "    else:\n"
        "        a = 2\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_elif_chain_untouched(tmp_path):
    # An elif (no literal `else:` header) is never flattened.
    src = (
        "def f(c, d):\n"
        "    if c:\n"
        "        return 1\n"
        "    elif d:\n"
        "        return 2\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_elif_chain_top_not_flattened(tmp_path):
    # The outer `if`/`elif`'s top branch (`if c: return 1`) is followed by an
    # `elif`, which parses as a nested `ast.If` in the orelse — there is NO
    # literal `else:` header right after `return 1`, so that branch is never
    # flattened. The outer `if` keeps its `elif` intact (only the inner `elif`'s
    # own real `else:` may be touched — see below).
    src = (
        "def f(c, d):\n"
        "    if c:\n"
        "        return 1\n"
        "    elif d:\n"
        "        x = 2\n"
        "    else:\n"
        "        x = 3\n"
    )
    rel, plan = _result(tmp_path, src)
    # The inner elif body (`x = 2`) is not a terminal, so its else is kept too —
    # nothing qualifies anywhere.
    assert not plan.new_contents
    assert not plan.blockers
    # The `elif` keyword is never rewritten into a bare `else`.
    assert "elif" in src


def test_nested_if_flattened(tmp_path):
    # Two independent qualifying ifs, the inner one nested in the outer's body.
    src = (
        "def f(c, d):\n"
        "    if c:\n"
        "        if d:\n"
        "            return 1\n"
        "        else:\n"
        "            return 2\n"
        "        return 9\n"
        "    else:\n"
        "        return 3\n"
    )
    rel, plan = _result(tmp_path, src)
    # Outer if body now ends in `return 9` (a terminal) -> outer else flattens;
    # inner if body ends in `return 1` -> inner else flattens. Two edits.
    assert plan.edits_by_file[rel] == 2
    assert plan.new_contents[rel] == (
        "def f(c, d):\n"
        "    if c:\n"
        "        if d:\n"
        "            return 1\n"
        "        return 2\n"
        "        return 9\n"
        "    return 3\n"
    )
    ast.parse(plan.new_contents[rel])


def test_multiple_occurrences_bottom_up(tmp_path):
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n"
        "\n"
        "def g(c):\n"
        "    if c:\n"
        "        return 3\n"
        "    else:\n"
        "        return 4\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.edits_by_file[rel] == 2
    assert plan.new_contents[rel] == (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    return 2\n"
        "\n"
        "def g(c):\n"
        "    if c:\n"
        "        return 3\n"
        "    return 4\n"
    )


def test_result_reparses_and_equivalent(tmp_path):
    before = (
        "def classify(n):\n"
        "    if n > 0:\n"
        "        return 'pos'\n"
        "    else:\n"
        "        if n == 0:\n"
        "            return 'zero'\n"
        "        return 'neg'\n"
    )
    rel, plan = _result(tmp_path, before)
    after = plan.new_contents[rel]
    assert ast.parse(after)  # re-parses
    for n in (-5, -1, 0, 1, 7):
        b_ns: dict = {}
        a_ns: dict = {}
        exec(compile(before, "<b>", "exec"), b_ns)
        exec(compile(after, "<a>", "exec"), a_ns)
        assert b_ns["classify"](n) == a_ns["classify"](n), n


def test_unparseable_module_blocks(tmp_path):
    rel, plan = _result(tmp_path, "def broken(:\n")
    assert plan.blockers
    assert not plan.new_contents
    assert not plan.ok


def test_noop_returns_empty_plan(tmp_path):
    rel, plan = _result(tmp_path, "x = 1 + 2\n")
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.ok


def test_fixture_path_excluded(tmp_path):
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n"
    )
    rel = "tests/test_thing.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / rel).write_text(src, encoding="utf-8")
    plan = plan_remove_redundant_else(tmp_path, rel)
    assert not plan.new_contents
    assert not plan.blockers


def test_missing_file_blocks(tmp_path):
    plan = plan_remove_redundant_else(tmp_path, "nope.py")
    assert plan.blockers
    assert not plan.ok


def test_objective_self_registered():
    from app.engine.objective_compiler import available_objectives
    assert "remove-redundant-else" in available_objectives()
