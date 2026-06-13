"""Tests for the accumulator-loop -> comprehension simplification transform."""

from __future__ import annotations

import ast

from app.execution.comprehension import (
    _is_fixture_path,
    plan_simplify_comprehension,
)
from app.execution.cross_file_rename import _py_files


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _exec_fn(source, name):
    """Compile ``source`` and return its top-level function ``name``."""
    namespace: dict = {}
    exec(compile(source, "<test>", "exec"), namespace)
    return namespace[name]


def _assert_equivalent(before, after, name, inputs):
    fn_before = _exec_fn(before, name)
    fn_after = _exec_fn(after, name)
    for arg in inputs:
        assert fn_before(arg) == fn_after(arg), arg


# ── canonical 2-statement accumulator ───────────────────────────────────────

def test_canonical_accumulator(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(x * 2)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "    out = [x * 2 for x in xs]" in new
    assert ".append" not in new  # loop collapsed
    ast.parse(new)
    _assert_equivalent(src, new, "f", [[], [1, 2, 3], range(4)])


# ── tuple target ────────────────────────────────────────────────────────────

def test_tuple_target(tmp_path):
    src = (
        "def f(items):\n"
        "    out = []\n"
        "    for k, v in items:\n"
        "        out.append(k)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "out = [k for k, v in items]" in new
    ast.parse(new)
    _assert_equivalent(src, new, "f", [[("a", 1), ("b", 2)], []])


# ── conservative: body with two statements untouched ────────────────────────

def test_two_statement_body_not_touched(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(x)\n"
        "        print(x)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers  # a no-op, not a failure


# ── conservative: append of a non-matching name untouched ───────────────────

def test_non_matching_append_name_not_touched(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        other.append(x)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.new_contents


# ── conservative: RHS not [] untouched ──────────────────────────────────────

def test_non_empty_list_rhs_not_touched(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = [0]\n"
        "    for x in xs:\n"
        "        out.append(x)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.new_contents


# ── conservative: for/else untouched ────────────────────────────────────────

def test_for_else_not_touched(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(x)\n"
        "    else:\n"
        "        out.append(-1)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.new_contents


# ── conservative: extra use of the name in the body untouched ───────────────

def test_extra_name_use_in_body_not_touched(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(len(out))\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.new_contents


# ── conservative: multi-line expr skipped ───────────────────────────────────

def test_multiline_expr_skipped(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(x +\n"
        "                   1)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.new_contents  # conservatively skipped


# ── conservative: starred / keyword append untouched ────────────────────────

def test_starred_arg_not_touched(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(*x)\n"
        "    return out\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.new_contents


# ── multiple independent occurrences in one module ──────────────────────────

def test_multiple_occurrences(tmp_path):
    src = (
        "def a(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(x * 2)\n"
        "    return out\n"
        "\n"
        "\n"
        "def b(ys):\n"
        "    acc = []\n"
        "    for y in ys:\n"
        "        acc.append(y - 1)\n"
        "    return acc\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert plan.ok
    assert plan.edits_by_file["m.py"] == 2
    new = plan.new_contents["m.py"]
    assert "out = [x * 2 for x in xs]" in new
    assert "acc = [y - 1 for y in ys]" in new
    ast.parse(new)
    _assert_equivalent(src, new, "a", [[1, 2], range(3)])
    _assert_equivalent(src, new, "b", [[5, 6], range(3)])


# ── indentation preserved for a nested accumulator ──────────────────────────

def test_nested_indentation_preserved(tmp_path):
    src = (
        "def f(rows):\n"
        "    if rows:\n"
        "        out = []\n"
        "        for r in rows:\n"
        "            out.append(r)\n"
        "        return out\n"
        "    return []\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "        out = [r for r in rows]" in new  # 8-space indent kept
    ast.parse(new)
    _assert_equivalent(src, new, "f", [[1, 2, 3], []])


# ── clean function: empty plan ──────────────────────────────────────────────

def test_clean_function_empty_plan(tmp_path):
    src = (
        "def f(x):\n"
        "    y = x * 2\n"
        "    return y + 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.edits_by_file


# ── assignment not immediately followed by the for ──────────────────────────

def test_intervening_statement_not_touched(tmp_path):
    src = (
        "def f(xs):\n"
        "    out = []\n"
        "    n = len(xs)\n"
        "    for x in xs:\n"
        "        out.append(x)\n"
        "    return out, n\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_comprehension(tmp_path, "m.py")
    assert not plan.new_contents  # for is not the next sibling


# ── unreadable / unparseable module ─────────────────────────────────────────

def test_missing_module_blocks(tmp_path):
    plan = plan_simplify_comprehension(tmp_path, "nope.py")
    assert not plan.ok
    assert plan.blockers


def test_syntax_error_blocks(tmp_path):
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    plan = plan_simplify_comprehension(tmp_path, "bad.py")
    assert not plan.ok
    assert any("doesn't parse" in b for b in plan.blockers)


# ── discovery via _py_files in a tmp_path project ───────────────────────────

def test_via_py_files_discovery(tmp_path):
    _write(
        tmp_path, "pkg/mod.py",
        "def doubled(xs):\n"
        "    out = []\n"
        "    for x in xs:\n"
        "        out.append(x * 2)\n"
        "    return out\n",
    )
    _write(tmp_path, "pkg/__init__.py", "")
    discovered = dict(_py_files(tmp_path))
    assert "pkg/mod.py" in discovered

    plan = plan_simplify_comprehension(tmp_path, "pkg/mod.py")
    assert plan.ok
    new = plan.new_contents["pkg/mod.py"]
    assert "out = [x * 2 for x in xs]" in new
    ast.parse(new)
    _assert_equivalent(discovered["pkg/mod.py"], new, "doubled", [[1, 2], range(3)])


# ── local _is_fixture_path mirrors dedup's ──────────────────────────────────

def test_is_fixture_path():
    assert _is_fixture_path("tests/test_x.py")
    assert _is_fixture_path("examples/demo.py")
    assert _is_fixture_path("pkg/test_helper.py")
    assert _is_fixture_path("a/fixtures/b.py")
    assert not _is_fixture_path("app/execution/comprehension.py")
