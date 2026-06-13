from __future__ import annotations

import ast

from app.execution.simplify_ternary_bool import plan_simplify_ternary_bool


def _write(tmp_path, source: str, rel: str = "app/m.py"):
    (tmp_path / "app").mkdir(exist_ok=True)
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _rewrite(tmp_path, source: str, rel: str = "app/m.py") -> str:
    """Run the transform and return the rewritten source (asserting it landed)."""
    _write(tmp_path, source, rel)
    plan = plan_simplify_ternary_bool(str(tmp_path), rel)
    assert not plan.blockers, plan.blockers
    assert plan.new_contents, "expected a rewrite"
    return plan.new_contents[rel]


# --- the two canonical forms ------------------------------------------------

def test_true_else_false_to_bool(tmp_path):
    out = _rewrite(tmp_path, "x = True if c else False\n")
    assert out == "x = bool(c)\n"
    ast.parse(out)


def test_false_else_true_to_not(tmp_path):
    out = _rewrite(tmp_path, "x = False if c else True\n")
    assert out == "x = not (c)\n"
    ast.parse(out)


def test_complex_condition_keeps_parens(tmp_path):
    # The parens around the test keep `and`-precedence correct.
    out = _rewrite(tmp_path, "x = True if a and b else False\n")
    assert out == "x = bool(a and b)\n"
    ast.parse(out)


def test_false_true_complex_condition(tmp_path):
    out = _rewrite(tmp_path, "x = False if a or b else True\n")
    assert out == "x = not (a or b)\n"
    ast.parse(out)


# --- shapes that must be left untouched -------------------------------------

def test_non_bool_branches_untouched(tmp_path):
    _write(tmp_path, "x = a if c else b\n")
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_one_zero_branches_untouched(tmp_path):
    # 1/0 are not the exact boolean Constants, even though `True is 1`-like
    # coincidences exist — we never trade on them.
    _write(tmp_path, "x = 1 if c else 0\n")
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_same_constant_untouched(tmp_path):
    _write(tmp_path, "x = True if c else True\n")
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_one_bool_one_nonbool_untouched(tmp_path):
    _write(tmp_path, "x = True if c else b\n")
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_multiline_ifexp_untouched(tmp_path):
    src = "x = (\n    True\n    if c\n    else False\n)\n"
    _write(tmp_path, src)
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


# --- nesting & multiplicity -------------------------------------------------

def test_ternary_inside_larger_expr(tmp_path):
    out = _rewrite(tmp_path, "y = f(True if c else False)\n")
    assert out == "y = f(bool(c))\n"
    ast.parse(out)


def test_two_occurrences_on_one_line(tmp_path):
    # Right-to-left application keeps both column spans valid.
    out = _rewrite(
        tmp_path, "z = (True if a else False, False if b else True)\n")
    assert out == "z = (bool(a), not (b))\n"
    ast.parse(out)


def test_multiple_lines_each_rewritten(tmp_path):
    out = _rewrite(
        tmp_path,
        "p = True if a else False\nq = False if b else True\n")
    assert out == "p = bool(a)\nq = not (b)\n"
    ast.parse(out)


# --- semantic equivalence ---------------------------------------------------

def test_semantically_equivalent_across_truthiness(tmp_path):
    before = "def g(c):\n    return True if c else False\n"
    out = _rewrite(tmp_path, before)
    assert out == "def g(c):\n    return bool(c)\n"
    for val in (0, 1, "", "x", [], [1], None, True, False):
        ns_before, ns_after = {}, {}
        exec(before, ns_before)
        exec(out, ns_after)
        assert ns_before["g"](val) == ns_after["g"](val)


def test_not_form_semantically_equivalent(tmp_path):
    before = "def g(c):\n    return False if c else True\n"
    out = _rewrite(tmp_path, before)
    assert out == "def g(c):\n    return not (c)\n"
    for val in (0, 1, "", "x", [], [1], None, True, False):
        ns_before, ns_after = {}, {}
        exec(before, ns_before)
        exec(out, ns_after)
        assert ns_before["g"](val) == ns_after["g"](val)


# --- safety: blockers, no-op, fixtures, registration ------------------------

def test_unparseable_module_blocks(tmp_path):
    _write(tmp_path, "def broken(:\n    pass\n")
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/m.py")
    assert plan.blockers


def test_missing_module_blocks(tmp_path):
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_noop_on_clean_module(tmp_path):
    _write(tmp_path, "x = 1\n")
    plan = plan_simplify_ternary_bool(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_fixture_subject_is_skipped(tmp_path):
    # Even a real match in a fixture/test path is left alone.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "x = True if c else False\n", encoding="utf-8")
    plan = plan_simplify_ternary_bool(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_deterministic(tmp_path):
    src = "x = True if c else False\n"
    _write(tmp_path, src)
    a = plan_simplify_ternary_bool(str(tmp_path), "app/m.py").new_contents
    b = plan_simplify_ternary_bool(str(tmp_path), "app/m.py").new_contents
    assert a == b


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "simplify-ternary-bool" in available_objectives()  # via the registry
