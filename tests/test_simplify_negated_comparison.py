from __future__ import annotations

import ast

from app.execution.simplify_negated_comparison import (
    plan_simplify_negated_comparison,
)


def _write(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Write a module under ``tmp_path`` and return its project-relative path."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return rel


def _plan(tmp_path, body: str, rel: str = "app/m.py"):
    _write(tmp_path, body, rel)
    return plan_simplify_negated_comparison(str(tmp_path), rel)


def _rewrite(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Run the plan over ``body`` and return the rewritten source (asserts it
    actually changed and re-parses)."""
    plan = _plan(tmp_path, body, rel)
    assert not plan.blockers, plan.blockers
    assert plan.new_contents, "expected a rewrite"
    new = plan.new_contents[rel]
    ast.parse(new)  # must re-parse
    return new


# --- core rewrites: each of the four ordering operators inverts -------------

def test_not_lt(tmp_path):
    assert _rewrite(tmp_path, "y = not a < b\n") == "y = a >= b\n"


def test_not_lte(tmp_path):
    assert _rewrite(tmp_path, "y = not a <= b\n") == "y = a > b\n"


def test_not_gt(tmp_path):
    assert _rewrite(tmp_path, "y = not a > b\n") == "y = a <= b\n"


def test_not_gte(tmp_path):
    assert _rewrite(tmp_path, "y = not a >= b\n") == "y = a < b\n"


def test_attribute_and_subscript_operands_preserved(tmp_path):
    new = _rewrite(tmp_path, "y = not obj.attr < data[key]\n")
    assert new == "y = obj.attr >= data[key]\n"


def test_call_operand_not_parenthesised(tmp_path):
    # Calls are atomic — no wrapping parens needed.
    new = _rewrite(tmp_path, "y = not f(1) > g(2)\n")
    assert new == "y = f(1) <= g(2)\n"


def test_parens_around_compare_dropped(tmp_path):
    # `not (a < b)` -> the redundant paren pair drops out.
    assert _rewrite(tmp_path, "y = not (a < b)\n") == "y = a >= b\n"


# --- precedence safety: low-precedence operands MUST be parenthesised -------

def test_low_precedence_left_operand_parenthesised(tmp_path):
    # `not (a or c) < b` must become `(a or c) >= b`, NEVER `a or c >= b` (H-family).
    new = _rewrite(tmp_path, "y = not (a or c) < b\n")
    assert new == "y = (a or c) >= b\n"


def test_low_precedence_right_operand_parenthesised(tmp_path):
    new = _rewrite(tmp_path, "y = not a < (b or c)\n")
    assert new == "y = a >= (b or c)\n"


def test_ternary_operand_parenthesised(tmp_path):
    new = _rewrite(tmp_path, "y = not a < (b if c else d)\n")
    assert new == "y = a >= (b if c else d)\n"


def test_low_precedence_operand_exec_equivalent(tmp_path):
    # Prove `not (a or c) < b` == `(a or c) >= b` for representative envs.
    new = _rewrite(tmp_path, "y = not (a or c) < b\n")
    assert new == "y = (a or c) >= b\n"
    for env in (
        {"a": 0, "c": 5, "b": 3},   # a or c -> 5
        {"a": 7, "c": 5, "b": 3},   # a or c -> 7
        {"a": 0, "c": 0, "b": 3},   # a or c -> 0
        {"a": 0, "c": 2, "b": 2},   # equal boundary
    ):
        before = eval("not (a or c) < b", dict(env))   # noqa: S307
        after = eval("(a or c) >= b", dict(env))        # noqa: S307
        assert before == after, env


# --- shapes we must NOT touch ----------------------------------------------

def test_not_eq_untouched(tmp_path):
    # `==` is EXCLUDED — owned by remove_double_negation (no double-register).
    plan = _plan(tmp_path, "y = not a == b\n")
    assert not plan.new_contents and not plan.blockers


def test_not_neq_untouched(tmp_path):
    # `!=` is EXCLUDED — owned by remove_double_negation.
    plan = _plan(tmp_path, "y = not a != b\n")
    assert not plan.new_contents and not plan.blockers


def test_not_in_untouched(tmp_path):
    # `in` is EXCLUDED — owned by fix_not_in_is.
    plan = _plan(tmp_path, "y = not a in b\n")
    assert not plan.new_contents and not plan.blockers


def test_not_is_untouched(tmp_path):
    # `is` is EXCLUDED — owned by fix_not_in_is.
    plan = _plan(tmp_path, "y = not a is b\n")
    assert not plan.new_contents and not plan.blockers


def test_chained_compare_untouched(tmp_path):
    # `not a < b < c` is a chained compare (len(ops) == 2) — left alone.
    plan = _plan(tmp_path, "y = not a < b < c\n")
    assert not plan.new_contents and not plan.blockers


def test_non_comparison_not_untouched(tmp_path):
    # `not x` — operand is a Name, not a Compare.
    plan = _plan(tmp_path, "y = not x\n")
    assert not plan.new_contents and not plan.blockers


def test_not_boolop_untouched(tmp_path):
    # `not (a < b or c)` — operand is a BoolOp, not a single Compare.
    plan = _plan(tmp_path, "y = not (a < b or c)\n")
    assert not plan.new_contents and not plan.blockers


def test_double_not_untouched(tmp_path):
    # `not not x` — inner is a UnaryOp, not a Compare (remove_double_negation owns it).
    plan = _plan(tmp_path, "y = not not x\n")
    assert not plan.new_contents and not plan.blockers


def test_multiline_untouched(tmp_path):
    # The UnaryOp spans two lines — the single-line splice is skipped.
    plan = _plan(tmp_path, "y = not (\n    a < b\n)\n")
    assert not plan.new_contents and not plan.blockers


# --- nested negation: outer wins, no overlapping splice ---------------------

def test_nested_negation_outer_wins(tmp_path):
    # `not not a < b`: outer UnaryOp's operand is a UnaryOp (not Compare) so the
    # outer never rewrites; only the inner `not a < b` is a candidate. The result
    # must still re-parse and only the inner compare inverts.
    new = _rewrite(tmp_path, "y = not (not a < b)\n")
    assert new == "y = not (a >= b)\n"


# --- multiple occurrences / ordering ----------------------------------------

def test_two_on_one_line_right_to_left(tmp_path):
    new = _rewrite(tmp_path, "y = (not a < b) or (not c > d)\n")
    assert new == "y = (a >= b) or (c <= d)\n"


def test_multiple_across_lines(tmp_path):
    body = "p = not a < b\nq = not c > d\nr = not e <= f\n"
    plan = _plan(tmp_path, body)
    assert plan.edits_by_file["app/m.py"] == 3
    assert plan.new_contents["app/m.py"] == (
        "p = a >= b\nq = c <= d\nr = e > f\n"
    )


# --- comments / surrounding formatting survive ------------------------------

def test_trailing_comment_survives(tmp_path):
    new = _rewrite(tmp_path, "y = not a < b  # bounds check\n")
    assert new == "y = a >= b  # bounds check\n"


# --- semantic equivalence (exec before/after) -------------------------------

def test_semantically_equivalent_all_operators(tmp_path):
    before = (
        "def f(a, b):\n"
        "    return (not a < b, not a <= b, not a > b, not a >= b)\n"
    )
    rel = _write(tmp_path, before)
    after = plan_simplify_negated_comparison(str(tmp_path), rel).new_contents[rel]
    assert "return (a >= b, a > b, a <= b, a < b)" in after
    ns_before: dict = {}
    ns_after: dict = {}
    exec(before, ns_before)
    exec(after, ns_after)
    cases = [(1, 2), (2, 1), (3, 3), (-1, -1), ("a", "b"), ("b", "a"), ("c", "c")]
    for a, b in cases:
        assert ns_before["f"](a, b) == ns_after["f"](a, b), (a, b)


# --- determinism ------------------------------------------------------------

def test_deterministic(tmp_path):
    body = "y = not a < b\nz = not (c or d) >= e\n"
    rel = _write(tmp_path, body)
    first = plan_simplify_negated_comparison(str(tmp_path), rel).new_contents[rel]
    second = plan_simplify_negated_comparison(str(tmp_path), rel).new_contents[rel]
    assert first == second
    assert first == "y = a >= b\nz = (c or d) < e\n"


# --- failure / no-op / fixture skip -----------------------------------------

def test_unparseable_module_blocks(tmp_path):
    plan = _plan(tmp_path, "def broken(:\n")
    assert plan.blockers
    assert not plan.new_contents


def test_missing_module_blocks(tmp_path):
    plan = plan_simplify_negated_comparison(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_noop_on_clean_module(tmp_path):
    plan = _plan(tmp_path, "x = 1\n")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_fixture_subject_is_skipped(tmp_path):
    # A test_ subject is excluded even though it has a matching shape.
    plan = _plan(tmp_path, "y = not a < b\n", rel="tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


# --- registration -----------------------------------------------------------

def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "simplify-negated-comparison" in available_objectives()
