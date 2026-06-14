from __future__ import annotations

from app.execution.remove_unreachable_after_terminator import plan_remove_unreachable_after_terminator


def _project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_noop_on_clean_module(tmp_path):
    _project(tmp_path)
    plan = plan_remove_unreachable_after_terminator(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_remove_unreachable_after_terminator(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    plan = plan_remove_unreachable_after_terminator(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "remove-unreachable-after-terminator" in available_objectives()  # discovered via the registry


def _write(tmp_path, src: str, rel: str = "app/m.py") -> str:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return rel


def _run(src: str, name: str, *args):
    ns: dict = {}
    exec(compile(src, "<m>", "exec"), ns)  # noqa: S102 - controlled test source
    return ns[name](*args)


def test_removes_code_after_return(tmp_path):
    rel = _write(tmp_path, "def f():\n    return 1\n    x = 2\n    return x\n")
    new = plan_remove_unreachable_after_terminator(str(tmp_path), rel).new_contents[rel]
    assert new == "def f():\n    return 1\n"
    assert _run(new, "f") == 1


def test_removes_code_after_raise(tmp_path):
    rel = _write(tmp_path, "def f():\n    raise ValueError('x')\n    return 1\n")
    new = plan_remove_unreachable_after_terminator(str(tmp_path), rel).new_contents[rel]
    assert new == "def f():\n    raise ValueError('x')\n"


def test_removes_after_break_and_continue(tmp_path):
    rel = _write(
        tmp_path,
        "def f(xs):\n"
        "    for x in xs:\n"
        "        if x:\n"
        "            break\n"
        "            print('dead')\n"   # unreachable after break
        "        continue\n"
        "        print('also dead')\n"  # unreachable after continue
        "    return 1\n",
    )
    new = plan_remove_unreachable_after_terminator(str(tmp_path), rel).new_contents[rel]
    assert "dead" not in new
    assert _run(new, "f", [1, 0]) == 1


def test_return_inside_if_keeps_reachable_tail(tmp_path):
    # The return is inside the if; the statement AFTER the if is reachable when
    # the condition is false, so nothing is removed.
    src = "def f(c):\n    if c:\n        return 1\n    return 2\n"
    rel = _write(tmp_path, src)
    plan = plan_remove_unreachable_after_terminator(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers  # untouched no-op
    assert _run(src, "f", True) == 1 and _run(src, "f", False) == 2


def test_trailing_def_blocks_the_occurrence(tmp_path):
    # A dead `def` after a return may be referenced by name elsewhere — skip.
    src = "def f():\n    return 1\n    def helper():\n        return 2\n"
    rel = _write(tmp_path, src)
    plan = plan_remove_unreachable_after_terminator(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_trailing_yield_blocks_the_occurrence(tmp_path):
    # Removing code containing a yield would change generator-ness — skip.
    src = "def f():\n    return\n    yield 1\n"
    rel = _write(tmp_path, src)
    plan = plan_remove_unreachable_after_terminator(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_terminator_last_is_noop(tmp_path):
    rel = _write(tmp_path, "def f():\n    x = 1\n    return x\n")
    plan = plan_remove_unreachable_after_terminator(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_determinism(tmp_path):
    rel = _write(tmp_path, "def f():\n    return 1\n    x = 2\n")
    a = plan_remove_unreachable_after_terminator(str(tmp_path), rel).new_contents[rel]
    b = plan_remove_unreachable_after_terminator(str(tmp_path), rel).new_contents[rel]
    assert a == b
