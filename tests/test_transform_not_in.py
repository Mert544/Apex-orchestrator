from __future__ import annotations

import ast

from app.execution.semantic.transforms import not_in_simplify as nis


def _apply(src: str) -> str | None:
    r = nis.apply("m.py", src, "simplify not-in")
    return r.patch_requests[0]["new_content"] if r else None


# --- rewrites -------------------------------------------------------------

def test_not_in_rewrite():
    out = _apply("x = not x in lst\n")
    assert out is not None
    assert "x not in lst" in out
    assert "not x in" not in out
    ast.parse(out)


def test_not_is_rewrite():
    out = _apply("y = not a is None\n")
    assert out is not None
    assert "a is not None" in out
    ast.parse(out)


def test_rewrite_inside_if():
    out = _apply("if not k in d:\n    pass\n")
    assert out is not None
    assert "k not in d" in out
    ast.parse(out)


def test_multiple_targets_all_rewritten():
    out = _apply("p = not a in b\nq = not c is d\n")
    assert out is not None
    assert "a not in b" in out
    assert "c is not d" in out
    r = nis.apply("m.py", "p = not a in b\nq = not c is d\n", "t")
    assert "2 negated comparison(s)" in r.rationale[0]


# --- refusals -------------------------------------------------------------

def test_refuse_equality():
    # `not a == b` -> `a != b` is a different transform; never touched.
    assert _apply("z = not a == b\n") is None


def test_refuse_ordering():
    # `not a < b` has no fused negated spelling here.
    assert _apply("z = not a < b\n") is None


def test_refuse_chained_compare():
    # `not a < b < c` — `not` negates the whole chain.
    assert _apply("z = not a < b < c\n") is None


def test_refuse_chained_membership():
    # Chained `in` — single-operator guard rejects it.
    assert _apply("z = not a in b in c\n") is None


def test_refuse_boolop():
    assert _apply("z = not (a and b)\n") is None


def test_refuse_already_idiomatic():
    # `a not in b` / `a is not b` are not `UnaryOp(Not, ...)` — no-op.
    assert _apply("z = a not in b\n") is None
    assert _apply("z = a is not b\n") is None


def test_refuse_double_negated_inner():
    # `not a not in b` — inner op is NotIn, not In; ignored (no double-negate).
    assert _apply("z = not a not in b\n") is None
    assert _apply("z = not a is not b\n") is None


def test_no_target_returns_none():
    assert _apply("x = 1 + 2\n") is None


def test_syntax_error_returns_none():
    assert _apply("def (:\n") is None


# --- invariants -----------------------------------------------------------

def test_deterministic():
    src = "v = not a in b\n"
    first = _apply(src)
    for _ in range(5):
        assert _apply(src) == first


def test_idempotent():
    src = "v = not a in b\n"
    once = _apply(src)
    assert once is not None
    # Re-running on the rewritten output is a no-op.
    assert _apply(once) is None


def test_output_always_parseable():
    for src in (
        "x = not x in lst\n",
        "y = not a is None\n",
        "if not k in d:\n    pass\n",
        "z = [v for v in xs if not v in seen]\n",
    ):
        out = _apply(src)
        if out is not None:
            ast.parse(out)  # never unparseable


def test_semantic_equality_not_in():
    # `not (a in b)` and `a not in b` evaluate identically.
    out = _apply("r = not 3 in [1, 2, 3]\n")
    assert out is not None
    g_before: dict = {}
    g_after: dict = {}
    exec("r = not 3 in [1, 2, 3]\n", g_before)
    exec(out, g_after)
    assert g_before["r"] == g_after["r"] is False


def test_semantic_equality_is_not():
    out = _apply("r = not None is None\n")
    assert out is not None
    g_before: dict = {}
    g_after: dict = {}
    exec("r = not None is None\n", g_before)
    exec(out, g_after)
    assert g_before["r"] == g_after["r"] is False
