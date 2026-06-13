"""Tests for the dead-code removal transform (app/execution/dead_code.py)."""

from __future__ import annotations

import ast

from app.execution.dead_code import plan_remove_dead_code


def _write(tmp_path, rel: str, source: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return rel


def test_return_then_dead_statement_removed(tmp_path):
    rel = _write(tmp_path, "m.py", "def f():\n    return 1\n    x = 2\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert new == "def f():\n    return 1\n"
    assert "x = 2" not in new
    ast.parse(new)  # re-parses
    assert plan.edits_by_file[rel] == 1
    assert plan.originals[rel] == "def f():\n    return 1\n    x = 2\n"


def test_raise_then_code_removed(tmp_path):
    rel = _write(
        tmp_path, "m.py",
        "def f():\n    raise ValueError()\n    cleanup()\n    more()\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert "cleanup()" not in new and "more()" not in new
    assert new == "def f():\n    raise ValueError()\n"
    ast.parse(new)


def test_break_then_code_removed(tmp_path):
    rel = _write(
        tmp_path, "m.py",
        "def f():\n    for i in range(3):\n        break\n        y = i\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert "y = i" not in new
    ast.parse(new)


def test_continue_then_code_removed(tmp_path):
    rel = _write(
        tmp_path, "m.py",
        "def f():\n    for i in range(3):\n        continue\n        z = i\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert "z = i" not in new
    ast.parse(new)


def test_terminal_as_last_statement_no_change(tmp_path):
    rel = _write(tmp_path, "m.py", "def f():\n    x = 1\n    return x\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert not plan.new_contents
    assert not plan.ok
    assert plan.edits_by_file == {}


def test_return_inside_if_does_not_kill_sibling(tmp_path):
    # The detector's rule: only a DIRECT-child terminal kills following siblings.
    rel = _write(
        tmp_path, "m.py",
        "def f(c):\n    if c:\n        return\n    print('after')\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert not plan.new_contents  # print is reachable — nothing removed
    assert not plan.ok


def test_multiple_dead_blocks_all_removed(tmp_path):
    source = (
        "def a():\n"
        "    return 1\n"
        "    dead_a = 1\n"
        "\n"
        "def b():\n"
        "    raise RuntimeError()\n"
        "    dead_b = 2\n"
        "    also_b = 3\n"
    )
    rel = _write(tmp_path, "m.py", source)
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    for marker in ("dead_a", "dead_b", "also_b"):
        assert marker not in new
    assert plan.edits_by_file[rel] == 2
    ast.parse(new)


def test_comments_on_dead_lines_go_with_them(tmp_path):
    # A trailing comment on/after a dead statement is itself dead and removed.
    source = (
        "def f():\n"
        "    return 1\n"
        "    x = 2  # this trailing comment is dead too\n"
    )
    rel = _write(tmp_path, "m.py", source)
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert "dead too" not in new
    assert "x = 2" not in new
    assert new == "def f():\n    return 1\n"


def test_module_level_dead_code_removed(tmp_path):
    # The module body is itself a block — raise at top level kills what follows.
    source = "import sys\nraise SystemExit()\nsys.stdout.write('x')\n"
    rel = _write(tmp_path, "m.py", source)
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert "sys.stdout.write" not in new
    ast.parse(new)


def test_live_code_formatting_preserved(tmp_path):
    source = (
        "def f():\n"
        "    # leading comment stays\n"
        "    a   =   1   # spacing preserved\n"
        "    return a\n"
        "    gone = True\n"
    )
    rel = _write(tmp_path, "m.py", source)
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert "# leading comment stays" in new
    assert "a   =   1   # spacing preserved" in new
    assert "gone = True" not in new


def test_functional_equivalence_before_and_after(tmp_path):
    source = (
        "def compute(n):\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total += i\n"
        "    return total\n"
        "    total = -999  # never runs\n"
    )
    rel = _write(tmp_path, "m.py", source)
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]

    before_ns: dict = {}
    after_ns: dict = {}
    exec(compile(source, "<before>", "exec"), before_ns)
    exec(compile(new, "<after>", "exec"), after_ns)
    for arg in (0, 1, 5, 10):
        assert before_ns["compute"](arg) == after_ns["compute"](arg)


def test_no_dead_code_is_noop(tmp_path):
    rel = _write(tmp_path, "m.py", "def f():\n    return 1\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert not plan.new_contents
    assert not plan.ok


def test_missing_module_blocks(tmp_path):
    plan = plan_remove_dead_code(tmp_path, "does_not_exist.py")
    assert plan.blockers
    assert not plan.ok
    assert not plan.new_contents


def test_unparseable_module_blocks(tmp_path):
    rel = _write(tmp_path, "broken.py", "def f(:\n    pass\n")
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.blockers
    assert not plan.ok


def test_plan_through_py_files_layout(tmp_path):
    # A _py_files-discoverable package layout, end-to-end through the plan.
    from app.execution.cross_file_rename import _py_files

    rel = _write(
        tmp_path, "pkg/mod.py",
        "def handler():\n    return 'ok'\n    unreachable_marker = 1\n")
    discovered = {r for r, _ in _py_files(tmp_path)}
    assert "pkg/mod.py" in discovered

    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    assert plan.old == "pkg/mod.py"
    assert plan.new == "remove-dead-code"
    assert "unreachable_marker" not in plan.new_contents[rel]
    assert "unreachable_marker" in plan.originals[rel]
    ast.parse(plan.new_contents[rel])


def test_try_finally_else_blocks(tmp_path):
    # try/except/else/finally bodies are all blocks the detector scans.
    source = (
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "        dead_try = 1\n"
        "    finally:\n"
        "        return 2\n"
        "        dead_finally = 2\n"
    )
    rel = _write(tmp_path, "m.py", source)
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.ok
    new = plan.new_contents[rel]
    assert "dead_try" not in new
    assert "dead_finally" not in new
    assert plan.edits_by_file[rel] == 2
    ast.parse(new)
