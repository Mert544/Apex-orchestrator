"""Characterization: the refactored ``_try_boolop`` decompositions in
``startswith_tuple`` and ``chain_comparison`` are byte-identical to the prior
single-function versions.

Each transform's ``plan_*`` path is fed a battery of source snippets — both the
convertible shapes and the many must-NOT-convert shapes (mixed methods/families,
multi-line booleans, side-effecting middles, wrong arity, keywords, starargs,
non-call values, three-way booleans, ...) — and the full resulting plan
(blockers, originals, new_contents, edits_by_file) is asserted exactly. This
pins the decomposition: same skip conditions, same rewrite strings, same
determinism.
"""

from __future__ import annotations

from app.execution.chain_comparison import plan_chain_comparison
from app.execution.startswith_tuple import plan_collapse_startswith


def _plan(tmp_path, planner, body: str, rel: str = "app/m.py"):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return planner(str(tmp_path), rel)


def _assert_rewrite(tmp_path, planner, body: str, expected: str) -> None:
    plan = _plan(tmp_path, planner, body)
    assert not plan.blockers
    assert plan.new_contents["app/m.py"] == expected
    assert plan.edits_by_file["app/m.py"] == 1
    assert plan.originals["app/m.py"] == body


def _assert_noop(tmp_path, planner, body: str) -> None:
    plan = _plan(tmp_path, planner, body)
    assert not plan.blockers
    assert not plan.new_contents
    assert not plan.edits_by_file


# --- startswith/endswith collapse: convertible ----------------------------

def test_sw_basic_startswith(tmp_path):
    _assert_rewrite(
        tmp_path, plan_collapse_startswith,
        "r = x.startswith(a) or x.startswith(b)\n",
        "r = x.startswith((a, b))\n")


def test_sw_endswith_attr_receiver(tmp_path):
    _assert_rewrite(
        tmp_path, plan_collapse_startswith,
        "r = path.name.endswith(c) or path.name.endswith(d)\n",
        "r = path.name.endswith((c, d))\n")


def test_sw_three_way(tmp_path):
    _assert_rewrite(
        tmp_path, plan_collapse_startswith,
        "r = x.startswith(a) or x.startswith(b) or x.startswith(c)\n",
        "r = x.startswith((a, b, c))\n")


def test_sw_dedup_preserves_first_seen(tmp_path):
    _assert_rewrite(
        tmp_path, plan_collapse_startswith,
        "r = x.startswith(a) or x.startswith(a)\n",
        "r = x.startswith((a))\n")


def test_sw_tuple_arg_flattened_and_deduped(tmp_path):
    _assert_rewrite(
        tmp_path, plan_collapse_startswith,
        "r = x.startswith(('a', 'b')) or x.startswith(('a', 'c'))\n",
        "r = x.startswith(('a', 'b', 'c'))\n")


# --- startswith/endswith collapse: must NOT convert -----------------------

def test_sw_mixed_methods_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.startswith(a) or x.endswith(b)\n")


def test_sw_different_receiver_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.startswith(a) or y.startswith(b)\n")


def test_sw_and_is_not_or(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.startswith(a) and x.startswith(b)\n")


def test_sw_single_value_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = bool(x.startswith(a))\n")


def test_sw_wrong_arity_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.startswith(a, b) or x.startswith(c)\n")
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.startswith() or x.startswith(c)\n")


def test_sw_starred_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.startswith(*a) or x.startswith(c)\n")


def test_sw_keyword_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.startswith(a, k=1) or x.startswith(c)\n")


def test_sw_non_method_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = x.foo(a) or x.foo(b)\n")


def test_sw_multiline_skipped(tmp_path):
    _assert_noop(tmp_path, plan_collapse_startswith,
                 "r = (\n  x.startswith(a) or\n  x.startswith(b)\n)\n")


# --- chain comparison: convertible ----------------------------------------

def test_ch_lt(tmp_path):
    _assert_rewrite(tmp_path, plan_chain_comparison,
                    "r = a < b and b < c\n", "r = a < b < c\n")


def test_ch_lte_family(tmp_path):
    _assert_rewrite(tmp_path, plan_chain_comparison,
                    "r = a < b and b <= c\n", "r = a < b <= c\n")


def test_ch_gt(tmp_path):
    _assert_rewrite(tmp_path, plan_chain_comparison,
                    "r = x > y and y > z\n", "r = x > y > z\n")


def test_ch_eq(tmp_path):
    _assert_rewrite(tmp_path, plan_chain_comparison,
                    "r = a == b and b == c\n", "r = a == b == c\n")


def test_ch_attr_chain_middle(tmp_path):
    _assert_rewrite(tmp_path, plan_chain_comparison,
                    "r = a < x.n.m and x.n.m < c\n", "r = a < x.n.m < c\n")


def test_ch_constant_middle(tmp_path):
    _assert_rewrite(tmp_path, plan_chain_comparison,
                    "r = a < 5 and 5 < c\n", "r = a < 5 < c\n")


def test_ch_call_outer_ok(tmp_path):
    _assert_rewrite(tmp_path, plan_chain_comparison,
                    "r = f() < b and b < c\n", "r = f() < b < c\n")


# --- chain comparison: must NOT convert -----------------------------------

def test_ch_mixed_direction_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison, "r = a < b and b > c\n")


def test_ch_different_middle_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison, "r = a < b and c < d\n")


def test_ch_not_eq_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison, "r = a != b and b != c\n")


def test_ch_is_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison, "r = a is b and b is c\n")


def test_ch_left_multi_op_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison, "r = a < b < c and c < d\n")


def test_ch_three_values_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison,
                 "r = a < b and b < c and c < d\n")


def test_ch_or_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison, "r = a < b or b < c\n")


def test_ch_call_middle_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison, "r = a < f() and f() < c\n")


def test_ch_subscript_middle_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison,
                 "r = a < x[0] and x[0] < c\n")


def test_ch_multiline_skipped(tmp_path):
    _assert_noop(tmp_path, plan_chain_comparison,
                 "r = (\n  a < b and\n  b < c\n)\n")


# --- shared scaffold paths (blockers / fixtures) --------------------------

def test_missing_module_blocks_both(tmp_path):
    for planner in (plan_collapse_startswith, plan_chain_comparison):
        plan = planner(str(tmp_path), "app/nope.py")
        assert plan.blockers


def test_fixture_subject_skipped_both(tmp_path):
    for planner in (plan_collapse_startswith, plan_chain_comparison):
        plan = planner(str(tmp_path), "tests/test_x.py")
        assert not plan.new_contents and not plan.blockers
