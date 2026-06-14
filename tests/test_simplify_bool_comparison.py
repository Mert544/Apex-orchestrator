from __future__ import annotations

import ast

import pytest

from app.execution.simplify_bool_comparison import (
    plan_simplify_bool_comparison,
)


def _write(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Write a module under ``tmp_path`` and return its project-relative path."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return rel


def _plan(tmp_path, body: str, rel: str = "app/m.py"):
    _write(tmp_path, body, rel)
    return plan_simplify_bool_comparison(str(tmp_path), rel)


def _rewrite(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Run the plan over ``body`` and return the rewritten source (asserts it
    actually changed and re-parses)."""
    plan = _plan(tmp_path, body, rel)
    assert not plan.blockers, plan.blockers
    assert plan.new_contents, "expected a rewrite"
    new = plan.new_contents[rel]
    ast.parse(new)  # must re-parse
    return new


# --- core rewrites: each of the eight forms (operand is a provable bool) ------
# We use a `Compare` operand `(a < b)` — always provably bool — so the rewrite
# fires. The compare needs wrapping parens at the splice site, which the
# precedence-safe splice supplies.

def test_eq_true(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) == True\n") == "y = (a < b)\n"


def test_eq_false(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) == False\n") == "y = not (a < b)\n"


def test_neq_true(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) != True\n") == "y = not (a < b)\n"


def test_neq_false(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) != False\n") == "y = (a < b)\n"


def test_is_true(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) is True\n") == "y = (a < b)\n"


def test_is_false(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) is False\n") == "y = not (a < b)\n"


def test_is_not_true(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) is not True\n") == "y = not (a < b)\n"


def test_is_not_false(tmp_path):
    assert _rewrite(tmp_path, "y = (a < b) is not False\n") == "y = (a < b)\n"


# --- mirrored: the bool literal on the LEFT --------------------------------

def test_true_on_left(tmp_path):
    assert _rewrite(tmp_path, "y = True == (a < b)\n") == "y = (a < b)\n"


def test_false_on_left(tmp_path):
    assert _rewrite(tmp_path, "y = False == (a < b)\n") == "y = not (a < b)\n"


def test_true_is_left(tmp_path):
    assert _rewrite(tmp_path, "y = True is (a < b)\n") == "y = (a < b)\n"


def test_false_is_not_left(tmp_path):
    assert _rewrite(tmp_path, "y = False is not (a < b)\n") == "y = (a < b)\n"


# --- the `not <x>` operand is also provably bool ----------------------------

def test_not_operand_eq_false(tmp_path):
    # `(not z) == False` -> `not (not z)`: the operand `not z` is provably bool.
    assert _rewrite(tmp_path, "y = (not z) == False\n") == "y = not (not z)\n"


def test_not_operand_is_true(tmp_path):
    assert _rewrite(tmp_path, "y = (not z) is True\n") == "y = (not z)\n"


# --- semantic equivalence: exec before/after for every rewritten shape ------

_OPERANDS = [
    "(a < b)",       # a Compare — provably bool
    "(a == b)",      # a Compare — provably bool
    "(not a)",       # a UnaryOp(Not) — provably bool
    "(a is b)",      # a Compare — provably bool
]

_FORMS = [
    "{x} == True",
    "{x} == False",
    "{x} != True",
    "{x} != False",
    "{x} is True",
    "{x} is False",
    "{x} is not True",
    "{x} is not False",
    "True == {x}",
    "False == {x}",
    "True != {x}",
    "False != {x}",
]

# A value matrix spanning every "shape" the spec calls out: bool, int, str,
# list, None — proving the operand's underlying type never breaks equivalence.
_VALUES = [True, False, 0, 1, 2, -1, "", "x", [], [0], None, 0.0, 3.5]


@pytest.mark.parametrize("operand", _OPERANDS)
@pytest.mark.parametrize("form", _FORMS)
def test_exec_equivalent_every_shape(tmp_path, operand, form):
    expr = form.format(x=operand)
    body = f"def f(a, b):\n    return {expr}\n"
    rel = _write(tmp_path, body)
    plan = plan_simplify_bool_comparison(str(tmp_path), rel)
    assert plan.new_contents, f"expected a rewrite for {expr!r}"
    after = plan.new_contents[rel]

    ns_before: dict = {}
    ns_after: dict = {}
    exec(body, ns_before)  # noqa: S102
    exec(after, ns_after)  # noqa: S102
    for a in _VALUES:
        for b in _VALUES:
            try:
                before_val = ns_before["f"](a, b)
            except TypeError:
                # An ordering compare on mixed types raises identically in both.
                with pytest.raises(TypeError):
                    ns_after["f"](a, b)
                continue
            assert before_val == ns_after["f"](a, b), (expr, a, b)
            # The rewrite of a bool-producing operand is ALSO a bool — same type.
            assert before_val is ns_after["f"](a, b), (expr, a, b)


# --- precedence safety: a low-precedence context must keep parens ------------

def test_low_precedence_context_or(tmp_path):
    # `c or (a < b) is False` -> `c or not (a < b)`, NEVER `c or not a < b`
    # (which would parse as `c or (not (a < b))`... actually `not` binds the
    # compare, but `not a < b` is `not (a < b)` — the danger is the operand
    # itself, kept wrapped here). The compare operand stays parenthesised.
    new = _rewrite(tmp_path, "y = c or (a < b) is False\n")
    assert new == "y = c or not (a < b)\n"


def test_low_precedence_operand_exec_equivalent(tmp_path):
    # Prove the parenthesised `not` rewrite preserves meaning across envs.
    new = _rewrite(tmp_path, "y = c or (a < b) is False\n")
    assert new == "y = c or not (a < b)\n"
    for env in (
        {"a": 1, "b": 2, "c": 0},     # a<b True -> is False -> False; c=0 falsy
        {"a": 2, "b": 1, "c": 0},     # a<b False -> is False -> True
        {"a": 2, "b": 1, "c": "z"},   # c truthy short-circuits
        {"a": 1, "b": 2, "c": 5},
    ):
        before = eval("c or (a < b) is False", dict(env))   # noqa: S307
        after = eval("c or not (a < b)", dict(env))         # noqa: S307
        assert before == after, env


def test_compare_operand_always_wrapped(tmp_path):
    # A bare Compare operand is non-atomic, so splice_operand wraps it: the
    # `not` form must read `not (a == b)`, never `not a == b`.
    new = _rewrite(tmp_path, "y = (a == b) != True\n")
    assert new == "y = not (a == b)\n"


# --- the UNSAFE `== True` / `is True` on a NON-bool operand: must be SKIPPED --

def test_eq_true_on_name_skipped(tmp_path):
    # `x == True` on a bare Name is NOT provably bool — `2 == True` is False but
    # `2` is truthy, so the rewrite would be unsound. We skip it untouched.
    plan = _plan(tmp_path, "y = x == True\n")
    assert not plan.new_contents and not plan.blockers


def test_eq_false_on_name_skipped(tmp_path):
    # `x == False` on a bare Name is unsound (`"" == False` is False but
    # `not ""` is True) — skipped.
    plan = _plan(tmp_path, "y = x == False\n")
    assert not plan.new_contents and not plan.blockers


def test_is_true_on_name_skipped(tmp_path):
    # `x is True` on a bare Name is unsound (`1 is True` is False) — skipped.
    plan = _plan(tmp_path, "y = x is True\n")
    assert not plan.new_contents and not plan.blockers


def test_call_operand_skipped(tmp_path):
    # A Call (even `isinstance(...)`) is NOT provably bool without proving the
    # callee is unshadowed — conservatively skipped.
    plan = _plan(tmp_path, "y = isinstance(x, int) == True\n")
    assert not plan.new_contents and not plan.blockers


def test_attribute_operand_skipped(tmp_path):
    plan = _plan(tmp_path, "y = obj.flag is True\n")
    assert not plan.new_contents and not plan.blockers


def test_boolop_operand_skipped(tmp_path):
    # `a or b` is NOT a bool — skipped.
    plan = _plan(tmp_path, "y = (a or b) == True\n")
    assert not plan.new_contents and not plan.blockers


# --- shapes we must NOT touch ----------------------------------------------

def test_non_bool_literal_skipped(tmp_path):
    # Comparing against a numeric literal `1` is not a boolean-literal compare.
    plan = _plan(tmp_path, "y = (a < b) == 1\n")
    assert not plan.new_contents and not plan.blockers


def test_none_literal_skipped(tmp_path):
    # `None` is not a bool literal (none-comparison is a different objective).
    plan = _plan(tmp_path, "y = (a < b) == None\n")
    assert not plan.new_contents and not plan.blockers


def test_both_sides_bool_skipped(tmp_path):
    # `True == False` is degenerate — no non-literal operand to keep.
    plan = _plan(tmp_path, "y = True == False\n")
    assert not plan.new_contents and not plan.blockers


def test_ordering_operator_skipped(tmp_path):
    # `<` against a bool is an ordering compare, never rewritten.
    plan = _plan(tmp_path, "y = (a < b) < True\n")
    assert not plan.new_contents and not plan.blockers


def test_chained_compare_skipped(tmp_path):
    # `(a < b) == True == c` is a chained compare (len(ops) == 2) — skipped.
    plan = _plan(tmp_path, "y = (a < b) == True == c\n")
    assert not plan.new_contents and not plan.blockers


def test_multiline_compare_skipped(tmp_path):
    # The Compare spans two lines — the single-line splice is skipped.
    plan = _plan(tmp_path, "y = (\n    a < b\n) == True\n")
    assert not plan.new_contents and not plan.blockers


# --- multiple occurrences / ordering ----------------------------------------

def test_two_on_one_line_right_to_left(tmp_path):
    new = _rewrite(tmp_path, "y = ((a < b) == True, (c > d) is False)\n")
    assert new == "y = ((a < b), not (c > d))\n"


def test_multiple_across_lines(tmp_path):
    body = (
        "p = (a < b) == True\n"
        "q = (c > d) is False\n"
        "r = (e == f) != False\n"
    )
    plan = _plan(tmp_path, body)
    assert plan.edits_by_file["app/m.py"] == 3
    assert plan.new_contents["app/m.py"] == (
        "p = (a < b)\n"
        "q = not (c > d)\n"
        "r = (e == f)\n"
    )


# --- comments / surrounding formatting survive ------------------------------

def test_trailing_comment_survives(tmp_path):
    new = _rewrite(tmp_path, "y = (a < b) is False  # noqa\n")
    assert new == "y = not (a < b)  # noqa\n"


# --- re-parse guard ---------------------------------------------------------

def test_reparse_guard_blocks(tmp_path, monkeypatch):
    # Force the rewrite to emit invalid source; the re-parse guard must block
    # the plan (no new_contents) rather than ship a broken module.
    import app.execution.simplify_bool_comparison as mod

    def _bad_apply(source, rewrites):
        return "def broken(:\n"  # never parses

    monkeypatch.setattr(mod, "_apply", _bad_apply)
    plan = _plan(tmp_path, "y = (a < b) == True\n")
    assert plan.blockers
    assert not plan.new_contents


# --- determinism ------------------------------------------------------------

def test_deterministic(tmp_path):
    body = "y = (a < b) == True\nz = c or (d > e) is False\n"
    rel = _write(tmp_path, body)
    first = plan_simplify_bool_comparison(str(tmp_path), rel).new_contents[rel]
    second = plan_simplify_bool_comparison(str(tmp_path), rel).new_contents[rel]
    assert first == second
    assert first == "y = (a < b)\nz = c or not (d > e)\n"


# --- failure / no-op / fixture skip -----------------------------------------

def test_unparseable_module_blocks(tmp_path):
    plan = _plan(tmp_path, "def broken(:\n")
    assert plan.blockers
    assert not plan.new_contents


def test_missing_module_blocks(tmp_path):
    plan = plan_simplify_bool_comparison(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_noop_on_clean_module(tmp_path):
    plan = _plan(tmp_path, "x = 1\n")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not failure


def test_fixture_subject_is_skipped(tmp_path):
    # A test_ subject is excluded even with a matching shape.
    plan = _plan(tmp_path, "y = (a < b) == True\n", rel="tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


# --- registration -----------------------------------------------------------

def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "simplify-bool-comparison" in available_objectives()
