from __future__ import annotations

import ast

from app.execution.chain_comparison import plan_chain_comparison


def _module(tmp_path, body: str, rel: str = "app/m.py"):
    """Write ``body`` into ``rel`` under ``tmp_path`` and plan a rewrite."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return plan_chain_comparison(str(tmp_path), rel)


def _rewritten(tmp_path, body: str) -> str:
    plan = _module(tmp_path, body)
    assert not plan.blockers
    assert plan.new_contents, "expected a rewrite"
    return plan.new_contents["app/m.py"]


# --- skeleton invariants (kept) -------------------------------------------

def test_noop_on_clean_module(tmp_path):
    plan = _module(tmp_path, "x = 1\n")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not failure


def test_missing_module_blocks(tmp_path):
    plan = plan_chain_comparison(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    plan = plan_chain_comparison(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "chain-comparison" in available_objectives()


# --- positive rewrites ----------------------------------------------------

def test_lt_chain(tmp_path):
    out = _rewritten(tmp_path, "r = a < b and b < c\n")
    assert out == "r = a < b < c\n"


def test_lte_chain(tmp_path):
    out = _rewritten(tmp_path, "r = a <= b and b <= c\n")
    assert out == "r = a <= b <= c\n"


def test_gt_chain(tmp_path):
    out = _rewritten(tmp_path, "r = x > y and y > z\n")
    assert out == "r = x > y > z\n"


def test_gte_mixed_family_chain(tmp_path):
    # Gt and GtE share a family — still chainable.
    out = _rewritten(tmp_path, "r = x > y and y >= z\n")
    assert out == "r = x > y >= z\n"


def test_eq_chain(tmp_path):
    out = _rewritten(tmp_path, "r = a == b and b == c\n")
    assert out == "r = a == b == c\n"


def test_attribute_middle(tmp_path):
    out = _rewritten(tmp_path, "r = a < x.n and x.n < c\n")
    assert out == "r = a < x.n < c\n"


def test_constant_middle(tmp_path):
    out = _rewritten(tmp_path, "r = a < 5 and 5 < c\n")
    assert out == "r = a < 5 < c\n"


def test_preserves_surrounding_code(tmp_path):
    body = "import os\n\n\ndef f(a, b, c):\n    return a < b and b < c  # note\n"
    out = _rewritten(tmp_path, body)
    assert out == (
        "import os\n\n\ndef f(a, b, c):\n    return a < b < c  # note\n"
    )


# --- negative: must be left untouched -------------------------------------

def test_different_middle_untouched(tmp_path):
    plan = _module(tmp_path, "r = a < b and c < d\n")
    assert not plan.new_contents and not plan.blockers


def test_side_effecting_call_middle_untouched(tmp_path):
    plan = _module(tmp_path, "r = a < f() and f() < c\n")
    assert not plan.new_contents and not plan.blockers


def test_subscript_middle_untouched(tmp_path):
    plan = _module(tmp_path, "r = a < d[k] and d[k] < c\n")
    assert not plan.new_contents and not plan.blockers


def test_mixed_family_untouched(tmp_path):
    plan = _module(tmp_path, "r = a < b and b > c\n")
    assert not plan.new_contents and not plan.blockers


def test_not_equal_untouched(tmp_path):
    plan = _module(tmp_path, "r = a != b and b != c\n")
    assert not plan.new_contents and not plan.blockers


def test_is_operator_untouched(tmp_path):
    plan = _module(tmp_path, "r = a is b and b is c\n")
    assert not plan.new_contents and not plan.blockers


def test_in_operator_untouched(tmp_path):
    plan = _module(tmp_path, "r = a in b and b in c\n")
    assert not plan.new_contents and not plan.blockers


def test_eq_vs_ne_family_untouched(tmp_path):
    # Eq and NotEq are not in the same family (NotEq isn't chainable here).
    plan = _module(tmp_path, "r = a == b and b != c\n")
    assert not plan.new_contents and not plan.blockers


def test_or_untouched(tmp_path):
    plan = _module(tmp_path, "r = a < b or b < c\n")
    assert not plan.new_contents and not plan.blockers


def test_three_term_and_untouched(tmp_path):
    # More than two values in the BoolOp — explicitly NOT folded.
    plan = _module(tmp_path, "r = a < b and b < c and c < d\n")
    assert not plan.new_contents and not plan.blockers


def test_multi_operator_compare_untouched(tmp_path):
    # The first comparison already chains (two ops) — not our two-value shape.
    plan = _module(tmp_path, "r = a < b < c and c < d\n")
    assert not plan.new_contents and not plan.blockers


def test_multiline_boolop_untouched(tmp_path):
    body = "r = (\n    a < b\n    and b < c\n)\n"
    plan = _module(tmp_path, body)
    assert not plan.new_contents and not plan.blockers


# --- robustness -----------------------------------------------------------

def test_unparseable_module_blocks(tmp_path):
    plan = _module(tmp_path, "def broken(:\n    pass\n")
    assert plan.blockers


def test_empty_plan_is_noop_not_failure(tmp_path):
    plan = _module(tmp_path, "x = 1\ny = 2\n")
    assert not plan.ok  # no new_contents
    assert not plan.blockers  # but not a failure either


def test_result_reparses(tmp_path):
    out = _rewritten(tmp_path, "r = a < b and b < c\n")
    ast.parse(out)  # raises on failure


def test_multiple_chains_in_one_module(tmp_path):
    body = "p = a < b and b < c\nq = x > y and y > z\n"
    out = _rewritten(tmp_path, body)
    assert out == "p = a < b < c\nq = x > y > z\n"


# --- semantic equivalence: exec before & after ----------------------------

def _eval(expr: str, env: dict) -> object:
    return eval(expr, {}, dict(env))  # noqa: S307 - controlled test inputs


def test_semantically_equivalent_across_inputs(tmp_path):
    # For each chainable shape, the rewritten chain evaluates identically to the
    # original `and` across a grid of inputs. The side-effect-free middle guard
    # is what makes a < b and b < c equal to a < b < c for ALL a, b, c.
    cases = [
        ("a < b and b < c", "a < b < c"),
        ("a <= b and b <= c", "a <= b <= c"),
        ("a > b and b > c", "a > b > c"),
        ("a == b and b == c", "a == b == c"),
    ]
    values = [0, 1, 2]
    for before, after in cases:
        for a in values:
            for b in values:
                for c in values:
                    env = {"a": a, "b": b, "c": c}
                    assert _eval(before, env) == _eval(after, env), (
                        before, after, env)


def test_low_precedence_edge_operand_is_parenthesised(tmp_path):
    # The x/z operands aren't side-effect-gated; a low-precedence one (`a or b`)
    # must be wrapped or `a or b < m < c` parses as `a or (b < m < c)` (H3).
    import itertools
    (tmp_path / "app").mkdir(exist_ok=True)
    src = "y = (a or b) < m and m < c\n"
    (tmp_path / "app" / "m.py").write_text(src, encoding="utf-8")
    new = plan_chain_comparison(str(tmp_path), "app/m.py").new_contents["app/m.py"]
    assert new == "y = (a or b) < m < c\n"
    for a, b, m, c in itertools.product([0, 1], repeat=4):
        env = {"a": a, "b": b, "m": m, "c": c}
        assert (eval("(a or b) < m and m < c", dict(env))  # noqa: S307
                == eval("(a or b) < m < c", dict(env)))    # noqa: S307
