"""Tests for the combine-nested-with develop transform and its objective."""

from __future__ import annotations

import ast
import contextlib

from app.execution.nested_with import plan_combine_nested_with


def _write(tmp_path, source: str, rel: str = "mod.py") -> str:
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return rel


def _result(tmp_path, source: str):
    rel = _write(tmp_path, source)
    return rel, plan_combine_nested_with(tmp_path, rel)


def test_two_nested_withs_merged(tmp_path):
    src = (
        "with A:\n"
        "    with B:\n"
        "        body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "with A, B:\n"
        "    body()\n"
    )
    assert plan.edits_by_file[rel] == 1
    assert not plan.blockers


def test_as_clauses_preserved(tmp_path):
    src = (
        "with open(a) as f:\n"
        "    with open(b) as g:\n"
        "        use(f, g)\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "with open(a) as f, open(b) as g:\n"
        "    use(f, g)\n"
    )


def test_three_deep_collapses_fully(tmp_path):
    src = (
        "with A:\n"
        "    with B:\n"
        "        with C:\n"
        "            body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "with A, B, C:\n"
        "    body()\n"
    )


def test_multi_statement_body_dedented(tmp_path):
    src = (
        "with A:\n"
        "    with B:\n"
        "        first()\n"
        "        second()\n"
        "        third()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "with A, B:\n"
        "    first()\n"
        "    second()\n"
        "    third()\n"
    )


def test_nested_under_function_indent(tmp_path):
    src = (
        "def run():\n"
        "    with A:\n"
        "        with B:\n"
        "            work()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "def run():\n"
        "    with A, B:\n"
        "        work()\n"
    )


def test_multi_item_headers_merged(tmp_path):
    src = (
        "with A, B:\n"
        "    with C, D:\n"
        "        body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert plan.new_contents[rel] == (
        "with A, B, C, D:\n"
        "    body()\n"
    )


def test_extra_statement_in_outer_body_untouched(tmp_path):
    src = (
        "with A:\n"
        "    with B:\n"
        "        body()\n"
        "    after()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_statement_before_inner_with_untouched(tmp_path):
    src = (
        "with A:\n"
        "    before()\n"
        "    with B:\n"
        "        body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_async_outer_untouched(tmp_path):
    src = (
        "async def run():\n"
        "    async with A:\n"
        "        with B:\n"
        "            body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_async_inner_untouched(tmp_path):
    src = (
        "async def run():\n"
        "    with A:\n"
        "        async with B:\n"
        "            body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_multiline_outer_header_untouched(tmp_path):
    src = (
        "with (\n"
        "    A\n"
        "):\n"
        "    with B:\n"
        "        body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_comment_on_with_line_untouched(tmp_path):
    src = (
        "with A:  # keep me\n"
        "    with B:\n"
        "        body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert not plan.new_contents
    assert not plan.blockers


def test_result_reparses(tmp_path):
    src = (
        "with A:\n"
        "    with B:\n"
        "        body()\n"
    )
    rel, plan = _result(tmp_path, src)
    assert ast.parse(plan.new_contents[rel])  # re-parses cleanly


def test_semantically_equivalent(tmp_path):
    # Two real context managers that record enter/exit order; the merged form
    # must behave identically.
    preamble = (
        "import contextlib\n"
        "log = []\n"
        "@contextlib.contextmanager\n"
        "def cm(name):\n"
        "    log.append(('enter', name))\n"
        "    try:\n"
        "        yield name\n"
        "    finally:\n"
        "        log.append(('exit', name))\n"
    )
    body = (
        "with cm('a') as x:\n"
        "    with cm('b') as y:\n"
        "        log.append(('body', x, y))\n"
    )
    rel, plan = _result(tmp_path, preamble + body)
    after_body = plan.new_contents[rel][len(preamble):]
    assert after_body == (
        "with cm('a') as x, cm('b') as y:\n"
        "    log.append(('body', x, y))\n"
    )

    before_ns: dict = {}
    after_ns: dict = {}
    exec(compile(preamble + body, "<before>", "exec"), before_ns)
    exec(compile(plan.new_contents[rel], "<after>", "exec"), after_ns)
    assert before_ns["log"] == after_ns["log"]
    assert before_ns["log"] == [
        ("enter", "a"), ("enter", "b"),
        ("body", "a", "b"),
        ("exit", "b"), ("exit", "a"),
    ]


def test_semantically_equivalent_with_exitstack_helpers(tmp_path):
    # contextlib.nullcontext managers nested two deep — exec before/after.
    preamble = (
        "import contextlib\n"
        "seen = []\n"
    )
    body = (
        "with contextlib.nullcontext('p') as p:\n"
        "    with contextlib.nullcontext('q') as q:\n"
        "        seen.append((p, q))\n"
    )
    rel, plan = _result(tmp_path, preamble + body)
    before_ns: dict = {"contextlib": contextlib}
    after_ns: dict = {"contextlib": contextlib}
    exec(compile(preamble + body, "<b>", "exec"), before_ns)
    exec(compile(plan.new_contents[rel], "<a>", "exec"), after_ns)
    assert before_ns["seen"] == after_ns["seen"] == [("p", "q")]


def test_unparseable_module_blocks(tmp_path):
    rel, plan = _result(tmp_path, "with A:\n    with B(:\n")
    assert plan.blockers
    assert not plan.new_contents
    assert not plan.ok


def test_noop_returns_empty_plan(tmp_path):
    rel, plan = _result(tmp_path, "with A:\n    body()\n")
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.ok


def test_fixture_path_excluded(tmp_path):
    src = (
        "with A:\n"
        "    with B:\n"
        "        body()\n"
    )
    rel = "tests/test_thing.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / rel).write_text(src, encoding="utf-8")
    plan = plan_combine_nested_with(tmp_path, rel)
    assert not plan.new_contents
    assert not plan.blockers


def test_missing_file_blocks(tmp_path):
    plan = plan_combine_nested_with(tmp_path, "nope.py")
    assert plan.blockers
    assert not plan.ok


def test_self_registration():
    from app.engine.objective_compiler import available_objectives

    assert "combine-nested-with" in available_objectives()
