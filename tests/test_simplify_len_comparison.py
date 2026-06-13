from __future__ import annotations

import ast

from app.execution.simplify_len_comparison import plan_simplify_len_comparison


def _write(tmp_path, source: str, rel: str = "app/m.py"):
    """Write ``source`` to ``tmp_path/<rel>`` (making the package dir) and plan."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return plan_simplify_len_comparison(str(tmp_path), rel)


# --- scaffold invariants ---------------------------------------------------

def test_noop_on_clean_module(tmp_path):
    plan = _write(tmp_path, "x = 1\n")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_simplify_len_comparison(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    # Even with a real target shape, a fixture path is excluded as a subject.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def f(x):\n    if len(x) == 0:\n        return 1\n", encoding="utf-8")
    plan = plan_simplify_len_comparison(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "simplify-len-comparison" in available_objectives()  # via the registry


# --- the four boolean-context rewrites -------------------------------------

def test_if_len_eq_0_becomes_not(tmp_path):
    plan = _write(tmp_path, "def f(x):\n    if len(x) == 0:\n        return 1\n")
    assert plan.new_contents["app/m.py"] == (
        "def f(x):\n    if not x:\n        return 1\n")
    assert plan.edits_by_file["app/m.py"] == 1
    ast.parse(plan.new_contents["app/m.py"])  # result re-parses


def test_while_len_gt_0_becomes_bool(tmp_path):
    plan = _write(tmp_path, "def f(q):\n    while len(q) > 0:\n        q.pop()\n")
    assert plan.new_contents["app/m.py"] == (
        "def f(q):\n    while bool(q):\n        q.pop()\n")


def test_assert_len_ne_0_becomes_bool(tmp_path):
    plan = _write(tmp_path, "def f(s):\n    assert len(s) != 0\n")
    assert plan.new_contents["app/m.py"] == "def f(s):\n    assert bool(s)\n"


def test_len_ge_1_becomes_bool(tmp_path):
    plan = _write(tmp_path, "def f(x):\n    if len(x) >= 1:\n        return 1\n")
    assert plan.new_contents["app/m.py"] == (
        "def f(x):\n    if bool(x):\n        return 1\n")


def test_inside_and_operand(tmp_path):
    plan = _write(
        tmp_path,
        "def f(a, ready):\n    if len(a) > 0 and ready:\n        return 1\n")
    assert plan.new_contents["app/m.py"] == (
        "def f(a, ready):\n    if bool(a) and ready:\n        return 1\n")


def test_inside_not_unaryop(tmp_path):
    plan = _write(tmp_path, "def f(x):\n    if not len(x) == 0:\n        return 1\n")
    assert plan.new_contents["app/m.py"] == (
        "def f(x):\n    if not not x:\n        return 1\n")


def test_ifexp_test_position(tmp_path):
    plan = _write(tmp_path, "def f(x):\n    return 1 if len(x) != 0 else 0\n")
    assert plan.new_contents["app/m.py"] == (
        "def f(x):\n    return 1 if bool(x) else 0\n")


def test_preserves_complex_x_source(tmp_path):
    # ``x``'s ORIGINAL source is kept verbatim, attribute/subscript and all.
    plan = _write(
        tmp_path,
        "def f(o):\n    if len(o.items[0]) == 0:\n        return 1\n")
    assert plan.new_contents["app/m.py"] == (
        "def f(o):\n    if not o.items[0]:\n        return 1\n")


# --- conservative skips (the safety crux) ----------------------------------

def test_non_boolean_context_assignment_untouched(tmp_path):
    plan = _write(tmp_path, "def f(x):\n    n = len(x) == 0\n    return n\n")
    assert not plan.new_contents and not plan.blockers


def test_return_value_context_untouched(tmp_path):
    # `return len(x) == 0` is a bool VALUE, not a boolean test -> leave it.
    plan = _write(tmp_path, "def f(x):\n    return len(x) == 0\n")
    assert not plan.new_contents and not plan.blockers


def test_wrong_constant_untouched(tmp_path):
    plan = _write(tmp_path, "def f(x):\n    if len(x) == 3:\n        return 1\n")
    assert not plan.new_contents and not plan.blockers


def test_wrong_operator_shape_untouched(tmp_path):
    # len(x) < 1 / len(x) >= 0 are NOT in the four exact shapes.
    plan = _write(tmp_path, "def f(x):\n    if len(x) < 1:\n        return 1\n")
    assert not plan.new_contents and not plan.blockers


def test_extra_len_args_untouched(tmp_path):
    # len(x, y) is not a bare one-arg len call -> left alone (it isn't even
    # callable at runtime, but the transform must not touch it regardless).
    plan = _write(tmp_path, "def f(x, y):\n    if len(x, y) == 0:\n        return 1\n")
    assert not plan.new_contents and not plan.blockers


def test_mirrored_form_untouched(tmp_path):
    plan = _write(tmp_path, "def f(x):\n    if 0 == len(x):\n        return 1\n")
    assert not plan.new_contents and not plan.blockers


def test_chained_comparison_untouched(tmp_path):
    # Two operators -> not the exact one-operator shape.
    plan = _write(tmp_path, "def f(x):\n    if 0 < len(x) < 5:\n        return 1\n")
    assert not plan.new_contents and not plan.blockers


def test_multiline_compare_untouched(tmp_path):
    src = "def f(x):\n    if len(\n        x\n    ) == 0:\n        return 1\n"
    plan = _write(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_unparseable_module_blocks(tmp_path):
    plan = _write(tmp_path, "def f(:\n    pass\n")
    assert plan.blockers and not plan.new_contents


# --- exec-equivalence ------------------------------------------------------

def _exec_fn(source: str):
    ns: dict = {}
    exec(compile(source, "<t>", "exec"), ns)
    return ns["f"]


def test_exec_equivalence_eq_0(tmp_path):
    before = "def f(x):\n    if len(x) == 0:\n        return 'empty'\n    return 'full'\n"
    plan = _write(tmp_path, before)
    after = plan.new_contents["app/m.py"]
    f_before, f_after = _exec_fn(before), _exec_fn(after)
    for value in ([], [1], [1, 2], "", "ab"):
        assert f_before(value) == f_after(value)


def test_exec_equivalence_gt_0_and(tmp_path):
    before = ("def f(a, ready):\n"
              "    if len(a) > 0 and ready:\n"
              "        return 'go'\n"
              "    return 'wait'\n")
    plan = _write(tmp_path, before)
    after = plan.new_contents["app/m.py"]
    f_before, f_after = _exec_fn(before), _exec_fn(after)
    for coll in ([], [1]):
        for ready in (True, False):
            assert f_before(coll, ready) == f_after(coll, ready)


def test_exec_equivalence_while_gt_0(tmp_path):
    before = ("def f(q):\n"
              "    seen = []\n"
              "    while len(q) > 0:\n"
              "        seen.append(q.pop())\n"
              "    return seen\n")
    plan = _write(tmp_path, before)
    after = plan.new_contents["app/m.py"]
    assert _exec_fn(before)([1, 2, 3]) == _exec_fn(after)([1, 2, 3])
    assert _exec_fn(before)([]) == _exec_fn(after)([])
