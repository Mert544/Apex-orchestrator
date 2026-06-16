from __future__ import annotations

import ast
import itertools

from app.execution.semantic.transforms import chained_comparison as cc


def _apply(src: str):
    return cc.apply("mod.py", src, "merge comparisons")


def _patched_source(src: str) -> str:
    result = _apply(src)
    assert result is not None
    return result.patch_requests[0]["new_content"]


# --------------------------------------------------------------------------
# Mergeable chains
# --------------------------------------------------------------------------

def test_basic_lt_chain_merges():
    src = "x = a < b and b < c\n"
    out = _patched_source(src)
    assert "a < b < c" in out
    # Re-parses cleanly.
    ast.parse(out)


def test_all_compatible_operator_chains_merge():
    cases = {
        "a < b and b < c": "a < b < c",
        "a <= b and b <= c": "a <= b <= c",
        "a < b and b <= c": "a < b <= c",
        "a > b and b > c": "a > b > c",
        "a >= b and b >= c": "a >= b >= c",
        "a > b and b >= c": "a > b >= c",
        "a == b and b == c": "a == b == c",
    }
    for expr, expected in cases.items():
        out = _patched_source(f"r = {expr}\n")
        assert expected in out, (expr, out)
        ast.parse(out)


def test_attribute_chain_middle_merges():
    src = "v = a < obj.lo.hi and obj.lo.hi < c\n"
    out = _patched_source(src)
    assert "a < obj.lo.hi < c" in out
    ast.parse(out)


def test_constant_middle_merges():
    src = "v = a < 5 and 5 < c\n"
    out = _patched_source(src)
    assert "a < 5 < c" in out
    ast.parse(out)


def test_semantically_equivalent_across_value_sets():
    # exec the original vs the rewrite for many (a, b, c) and require identical bool.
    exprs = [
        "a < b and b < c",
        "a <= b and b <= c",
        "a > b and b > c",
        "a >= b and b >= c",
        "a == b and b == c",
        "a < b and b <= c",
    ]
    values = [-1, 0, 1, 2, 5]
    for expr in exprs:
        out = _patched_source(f"_result = {expr}\n")
        merged_expr = out.split("=", 1)[1].strip()
        for a, b, c in itertools.product(values, repeat=3):
            env = {"a": a, "b": b, "c": c}
            orig = eval(expr, {}, dict(env))
            new = eval(merged_expr, {}, dict(env))
            assert orig == new, (expr, merged_expr, a, b, c)


# --------------------------------------------------------------------------
# Refusals -> None
# --------------------------------------------------------------------------

def test_different_middle_term_refused():
    assert _apply("v = a < b and d < c\n") is None


def test_side_effectful_middle_call_refused():
    assert _apply("v = f() < b and b < c\n") is None
    assert _apply("v = a < f() and f() < c\n") is None


def test_subscript_middle_refused():
    assert _apply("v = a < m[0] and m[0] < c\n") is None


def test_three_way_and_unrelated_term_refused():
    assert _apply("v = a < b and b < c and z\n") is None


def test_single_compare_refused():
    assert _apply("v = a < b\n") is None


def test_incompatible_direction_refused():
    # Up vs down: a < b and b > c is NOT a legal/equivalent chain.
    assert _apply("v = a < b and b > c\n") is None
    assert _apply("v = a <= b and b >= c\n") is None


def test_eq_mixed_with_inequality_refused():
    assert _apply("v = a == b and b < c\n") is None


def test_or_not_merged():
    assert _apply("v = a < b or b < c\n") is None


def test_non_compare_arms_refused():
    assert _apply("v = a and b\n") is None


def test_syntax_error_returns_none():
    assert _apply("def broken(:\n") is None


def test_no_match_returns_none():
    assert _apply("x = 1\ny = 2\n") is None


# --------------------------------------------------------------------------
# Determinism & never-unparseable
# --------------------------------------------------------------------------

def test_determinism():
    src = "v = a < b and b < c\n"
    first = _apply(src)
    for _ in range(5):
        again = _apply(src)
        assert again is not None and first is not None
        assert again.patch_requests[0]["new_content"] == first.patch_requests[0]["new_content"]
        assert again.transform_type == first.transform_type


def test_output_always_parseable_over_many_inputs():
    snippets = [
        "v = a < b and b < c\n",
        "v = a <= b and b <= c\n",
        "v = a == b and b == c\n",
        "w = (a < b and b < c) and (p < q and q < r)\n",
        "v = a < obj.x and obj.x < c\n",
    ]
    for src in snippets:
        result = _apply(src)
        if result is not None:
            ast.parse(result.patch_requests[0]["new_content"])


def test_nested_double_chain_merges_both():
    src = "w = (a < b and b < c) and (p < q and q < r)\n"
    out = _patched_source(src)
    ast.parse(out)
    assert "a < b < c" in out
    assert "p < q < r" in out


def test_preserves_trailing_newline():
    src = "v = a < b and b < c\n"
    out = _patched_source(src)
    assert out.endswith("\n")
