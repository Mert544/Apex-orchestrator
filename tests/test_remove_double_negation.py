from __future__ import annotations

import ast

from app.execution.remove_double_negation import plan_remove_double_negation


def _project(tmp_path, body="x = 1\n"):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    return tmp_path


def _rewrite(tmp_path, body):
    """Helper: run the plan over a one-module project, return new source (or None
    if the plan is an empty no-op) and the plan itself."""
    _project(tmp_path, body)
    plan = plan_remove_double_negation(str(tmp_path), "app/m.py")
    new = plan.new_contents.get("app/m.py")
    return new, plan


# --- scaffold invariants -------------------------------------------------

def test_noop_on_clean_module(tmp_path):
    _project(tmp_path)
    plan = plan_remove_double_negation(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_remove_double_negation(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    plan = plan_remove_double_negation(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "remove-double-negation" in available_objectives()  # via the registry


# --- the six comparison inversions ---------------------------------------

def test_invert_eq(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (a == b)\n")
    assert new == "r = a != b\n"


def test_invert_noteq(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (a != b)\n")
    assert new == "r = a == b\n"


def test_invert_is(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (a is b)\n")
    assert new == "r = a is not b\n"


def test_invert_is_not(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (a is not b)\n")
    assert new == "r = a is b\n"


def test_invert_in(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (a in b)\n")
    assert new == "r = a not in b\n"


def test_invert_not_in(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (a not in b)\n")
    assert new == "r = a in b\n"


def test_invert_without_parens(tmp_path):
    # `not a == b` parses as `not (a == b)` — Compare binds tighter than `not`.
    new, _ = _rewrite(tmp_path, "r = not a == b\n")
    assert new == "r = a != b\n"


# --- double negation ------------------------------------------------------

def test_double_negation(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not not x\n")
    assert new == "r = bool(x)\n"


def test_double_negation_call_operand(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not not foo()\n")
    assert new == "r = bool(foo())\n"


# --- the SKIP cases -------------------------------------------------------

def test_ordering_lt_untouched(tmp_path):
    # not (a < b) is a >= b only on a total order — floats/NaN make it unsafe.
    new, plan = _rewrite(tmp_path, "r = not (a < b)\n")
    assert new is None and not plan.blockers


def test_ordering_all_comparators_untouched(tmp_path):
    for op in ("<", "<=", ">", ">="):
        new, plan = _rewrite(tmp_path, f"r = not (a {op} b)\n")
        assert new is None and not plan.blockers, op


def test_plain_not_call_untouched(tmp_path):
    # not f() is neither a Compare nor a double-not — left alone.
    new, plan = _rewrite(tmp_path, "r = not foo()\n")
    assert new is None and not plan.blockers


def test_plain_not_name_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "r = not x\n")
    assert new is None and not plan.blockers


def test_chained_compare_untouched(tmp_path):
    # not a == b == c has two operators — never a partial rewrite.
    new, plan = _rewrite(tmp_path, "r = not a == b == c\n")
    assert new is None and not plan.blockers


def test_chained_membership_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "r = not a in b in c\n")
    assert new is None and not plan.blockers


def test_multiline_unaryop_untouched(tmp_path):
    body = "r = not (\n    a == b\n)\n"
    new, plan = _rewrite(tmp_path, body)
    assert new is None and not plan.blockers


# --- operand fidelity -----------------------------------------------------

def test_attribute_and_subscript_operands_preserved(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (obj.attr == data['k'])\n")
    assert new == "r = obj.attr != data['k']\n"


def test_call_operands_preserved(tmp_path):
    new, _ = _rewrite(tmp_path, "r = not (len(xs) is None)\n")
    assert new == "r = len(xs) is not None\n"


def test_two_occurrences_one_line_right_to_left(tmp_path):
    new, plan = _rewrite(tmp_path, "r = (not (a == b), not (c in d))\n")
    assert new == "r = (a != b, c not in d)\n"
    assert plan.edits_by_file["app/m.py"] == 2


def test_mixed_compare_and_double_negation_one_line(tmp_path):
    new, plan = _rewrite(tmp_path, "r = (not (a is b), not not y)\n")
    assert new == "r = (a is not b, bool(y))\n"
    assert plan.edits_by_file["app/m.py"] == 2


# --- exec-equivalence across representative inputs ------------------------

def _exec_value(src_expr, env):
    """Evaluate ``src_expr`` (a single expression) in a fresh namespace."""
    ns = dict(env)
    return eval(compile(ast.parse(src_expr, mode="eval"), "<x>", "eval"), {}, ns)


def test_exec_equivalence_representative_inputs(tmp_path):
    # Each pair: a negated form that IS rewritten, checked against its result
    # under varied bindings. The rewrite must be semantically identical.
    cases = [
        ("not (a == b)", [{"a": 1, "b": 1}, {"a": 1, "b": 2}]),
        ("not (a != b)", [{"a": 1, "b": 1}, {"a": 1, "b": 2}]),
        ("not (a is b)", [{"a": None, "b": None}, {"a": 1, "b": 2}]),
        ("not (a is not b)", [{"a": None, "b": None}, {"a": 1, "b": 2}]),
        ("not (a in b)", [{"a": 1, "b": [1, 2]}, {"a": 3, "b": [1, 2]}]),
        ("not (a not in b)", [{"a": 1, "b": [1, 2]}, {"a": 3, "b": [1, 2]}]),
        ("not not x", [{"x": 0}, {"x": 5}, {"x": ""}, {"x": [1]}]),
    ]
    for expr, envs in cases:
        new, _ = _rewrite(tmp_path, f"r = {expr}\n")
        assert new is not None, expr
        rewritten = new[len("r = "):].rstrip("\n")
        for env in envs:
            assert _exec_value(expr, env) == _exec_value(rewritten, env), (
                expr, rewritten, env)


def test_ordering_left_alone_is_correct(tmp_path):
    # The transform must NOT rewrite ordering: under NaN, neither `not (a < b)`
    # nor a naive `a >= b` agree, which is exactly why we skip it. Confirm we
    # leave it untouched so the unsafe rewrite never happens.
    new, plan = _rewrite(tmp_path, "r = not (a < b)\n")
    assert new is None and not plan.blockers
    nan = float("nan")
    # Sanity: the unsafe rewrite WOULD disagree under NaN, justifying the skip.
    assert _exec_value("not (a < b)", {"a": nan, "b": 1.0}) is True
    assert _exec_value("a >= b", {"a": nan, "b": 1.0}) is False


# --- blocker / no-op paths ------------------------------------------------

def test_unparseable_module_blocks(tmp_path):
    new, plan = _rewrite(tmp_path, "def broken(:\n    pass\n")
    assert new is None and plan.blockers


def test_no_negations_is_noop(tmp_path):
    new, plan = _rewrite(tmp_path, "r = a == b\nq = a in b\n")
    assert new is None and not plan.blockers


def test_triple_not_collapses_outer_only(tmp_path):
    # not not not x yields overlapping candidate spans; the contained inner span
    # is dropped so the OUTER rewrite (covering the whole expression) lands once,
    # producing a single clean, re-parseable splice — never a corrupted module.
    new, plan = _rewrite(tmp_path, "r = not not not x\n")
    assert new == "r = bool(not x)\n"
    ast.parse(new)  # re-parses
    assert plan.edits_by_file["app/m.py"] == 1
    for env in ({"x": 0}, {"x": 5}, {"x": ""}, {"x": [1]}):
        assert _exec_value("not not not x", env) == _exec_value("bool(not x)", env)


def test_double_negation_inside_compare_operand(tmp_path):
    # The compare's operand IS a double-not, but the outer node is the compare,
    # not a UnaryOp — only the inner `not not y` matches and rewrites in place.
    # The user's explicit parens are outside the UnaryOp span, so they survive.
    new, _ = _rewrite(tmp_path, "r = (not not y) == z\n")
    assert new == "r = (bool(y)) == z\n"
    ast.parse(new)
