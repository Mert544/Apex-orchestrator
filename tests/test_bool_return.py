"""Tests for the bool-return simplification transform."""

from __future__ import annotations

import ast

from app.execution.bool_return import (
    _is_fixture_path,
    plan_simplify_bool_return,
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


# ── if/else True/False ──────────────────────────────────────────────────────

def test_if_else_true_false(tmp_path):
    src = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "return bool(x > 0)" in new
    ast.parse(new)  # re-parses
    _assert_equivalent(src, new, "f", [-2, -1, 0, 1, 5])


def test_if_else_false_true_swap(tmp_path):
    src = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return False\n"
        "    else:\n"
        "        return True\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "return not (x > 0)" in new
    ast.parse(new)
    _assert_equivalent(src, new, "f", [-2, -1, 0, 1, 5])


# ── no-else form ────────────────────────────────────────────────────────────

def test_no_else_true_false(tmp_path):
    src = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return True\n"
        "    return False\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "return bool(x > 0)" in new
    assert "return False" not in new  # trailing return collapsed
    ast.parse(new)
    _assert_equivalent(src, new, "f", [-2, -1, 0, 1, 5])


def test_no_else_false_true_swap(tmp_path):
    src = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return False\n"
        "    return True\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "return not (x > 0)" in new
    ast.parse(new)
    _assert_equivalent(src, new, "f", [-2, -1, 0, 1, 5])


# ── conservative: never touch non-bool returns ──────────────────────────────

def test_non_bool_return_not_touched(tmp_path):
    src = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return x\n"
        "    else:\n"
        "        return False\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers  # a no-op, not a failure


def test_non_bool_constant_return_not_touched(tmp_path):
    # ``return 1`` / ``return None`` are constants but not booleans.
    src = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return 1\n"
        "    else:\n"
        "        return 0\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert not plan.new_contents


def test_same_constant_both_branches_not_touched(tmp_path):
    src = (
        "def f(x):\n"
        "    if x > 0:\n"
        "        return True\n"
        "    else:\n"
        "        return True\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert not plan.new_contents


# ── conservative: multi-line condition skipped ──────────────────────────────

def test_multiline_condition_skipped(tmp_path):
    src = (
        "def f(x):\n"
        "    if (x > 0 and\n"
        "            x < 10):\n"
        "        return True\n"
        "    else:\n"
        "        return False\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert not plan.new_contents  # conservatively skipped


# ── clean function: empty plan ──────────────────────────────────────────────

def test_clean_function_empty_plan(tmp_path):
    src = (
        "def f(x):\n"
        "    y = x * 2\n"
        "    return y + 1\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert not plan.ok
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.edits_by_file


# ── multiple rewrites in one module, applied bottom-up ──────────────────────

def test_multiple_rewrites_preserve_lines(tmp_path):
    src = (
        "def a(x):\n"
        "    if x > 0:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n"
        "\n"
        "\n"
        "def b(y):\n"
        "    if y < 0:\n"
        "        return False\n"
        "    return True\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert plan.ok
    assert plan.edits_by_file["m.py"] == 2
    new = plan.new_contents["m.py"]
    assert "return bool(x > 0)" in new
    assert "return not (y < 0)" in new
    ast.parse(new)
    _assert_equivalent(src, new, "a", [-1, 0, 1])
    _assert_equivalent(src, new, "b", [-1, 0, 1])


# ── indentation preserved for nested if ─────────────────────────────────────

def test_nested_indentation_preserved(tmp_path):
    src = (
        "def f(x):\n"
        "    for _ in range(1):\n"
        "        if x > 0:\n"
        "            return True\n"
        "        else:\n"
        "            return False\n"
    )
    _write(tmp_path, "m.py", src)
    plan = plan_simplify_bool_return(tmp_path, "m.py")
    assert plan.ok
    new = plan.new_contents["m.py"]
    assert "        return bool(x > 0)" in new  # 8-space indent kept
    ast.parse(new)
    _assert_equivalent(src, new, "f", [-1, 0, 1])


# ── unreadable / unparseable module ─────────────────────────────────────────

def test_missing_module_blocks(tmp_path):
    plan = plan_simplify_bool_return(tmp_path, "nope.py")
    assert not plan.ok
    assert plan.blockers


def test_syntax_error_blocks(tmp_path):
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    plan = plan_simplify_bool_return(tmp_path, "bad.py")
    assert not plan.ok
    assert any("doesn't parse" in b for b in plan.blockers)


# ── discovery via _py_files in a tmp_path project ───────────────────────────

def test_via_py_files_discovery(tmp_path):
    _write(
        tmp_path, "pkg/mod.py",
        "def is_pos(x):\n"
        "    if x > 0:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n",
    )
    _write(tmp_path, "pkg/__init__.py", "")
    discovered = dict(_py_files(tmp_path))
    assert "pkg/mod.py" in discovered

    plan = plan_simplify_bool_return(tmp_path, "pkg/mod.py")
    assert plan.ok
    new = plan.new_contents["pkg/mod.py"]
    assert "return bool(x > 0)" in new
    ast.parse(new)
    _assert_equivalent(discovered["pkg/mod.py"], new, "is_pos", [-1, 0, 2])


# ── local _is_fixture_path mirrors dedup's ──────────────────────────────────

def test_is_fixture_path():
    assert _is_fixture_path("tests/test_x.py")
    assert _is_fixture_path("examples/demo.py")
    assert _is_fixture_path("pkg/test_helper.py")
    assert _is_fixture_path("a/fixtures/b.py")
    assert not _is_fixture_path("app/execution/bool_return.py")
