from __future__ import annotations

import ast

from app.execution.semantic.transforms import redundant_lambda as rl


def _apply(src: str) -> str | None:
    r = rl.apply("m.py", src, "drop redundant lambda")
    return r.patch_requests[0]["new_content"] if r else None


# ---------------------------------------------------------------------------
# Rewrites that should fire.
# ---------------------------------------------------------------------------

def test_single_param_forwarding():
    out = _apply("xs = sorted(ys, key=lambda x: f(x))\n")
    assert out == "xs = sorted(ys, key=f)\n"
    ast.parse(out)


def test_two_param_forwarding():
    out = _apply("r = reduce(lambda a, b: g(a, b), xs)\n")
    assert out == "r = reduce(g, xs)\n"
    ast.parse(out)


def test_attribute_chain_callable():
    out = _apply("h = lambda x: mod.sub.fn(x)\n")
    assert out == "h = mod.sub.fn\n"
    ast.parse(out)


def test_result_type_and_rationale():
    r = rl.apply("m.py", "z = lambda x: f(x)\n", "t")
    assert r is not None
    assert r.transform_type == "drop_redundant_lambda"
    assert r.rationale and "redundant" in r.rationale[0].lower()
    assert r.patch_requests[0]["expected_old_content"] == "z = lambda x: f(x)\n"


# ---------------------------------------------------------------------------
# Refusals.
# ---------------------------------------------------------------------------

def test_refuse_reordered_args():
    assert _apply("z = lambda a, b: g(b, a)\n") is None


def test_refuse_extra_arg():
    assert _apply("z = lambda a, b: g(a, b, c)\n") is None


def test_refuse_partial_application():
    assert _apply("z = lambda x: g(x, 1)\n") is None


def test_refuse_dropped_arg():
    assert _apply("z = lambda a, b: g(a)\n") is None


def test_refuse_keyword_in_call():
    assert _apply("z = lambda x: g(x, k=1)\n") is None


def test_refuse_star_unpacking():
    assert _apply("z = lambda x: g(*x)\n") is None


def test_refuse_body_not_a_call():
    # attribute access, not a call — the `key=lambda x: x.lower` real case.
    assert _apply("z = lambda x: x.lower\n") is None


def test_refuse_body_is_name():
    assert _apply("z = lambda x: x\n") is None


def test_refuse_body_binop():
    assert _apply("z = lambda x: x + 1\n") is None


def test_refuse_callable_is_itself_a_call():
    assert _apply("z = lambda x: factory()(x)\n") is None


def test_refuse_callable_is_subscript():
    assert _apply("z = lambda x: tbl[0](x)\n") is None


def test_refuse_default_param():
    assert _apply("z = lambda a, b=1: g(a, b)\n") is None


def test_refuse_vararg():
    assert _apply("z = lambda *a: g(a)\n") is None


def test_refuse_kwarg():
    assert _apply("z = lambda **k: g(k)\n") is None


def test_refuse_kwonly_param():
    assert _apply("z = lambda x, *, y: g(x, y)\n") is None


def test_refuse_no_params():
    assert _apply("z = lambda: f()\n") is None


def test_refuse_arg_is_constant_not_name():
    assert _apply("z = lambda a: g(1)\n") is None


# ---------------------------------------------------------------------------
# Robustness.
# ---------------------------------------------------------------------------

def test_syntax_error_returns_none():
    assert _apply("def f(:\n") is None


def test_no_lambda_returns_none():
    assert _apply("def f(x):\n    return x\n") is None


def test_multiline_lambda_skipped():
    # End-lineno != lineno; splice is skipped to stay exact -> no-op.
    src = "z = lambda x: f(\n    x)\n"
    assert _apply(src) is None


def test_determinism():
    src = "a = lambda x: f(x)\nb = lambda p, q: h(p, q)\n"
    first = _apply(src)
    assert first is not None
    assert first == _apply(src)


def test_idempotent():
    src = "z = lambda x: f(x)\n"
    once = _apply(src)
    assert once is not None
    assert _apply(once) is None


def test_multiple_lambdas_one_line_each():
    src = "a = lambda x: f(x)\nb = lambda u, v: g(u, v)\n"
    out = _apply(src)
    assert out == "a = f\nb = g\n"
    ast.parse(out)


def test_never_unparseable():
    # A grab bag of forwarding + non-forwarding lambdas; output must parse.
    src = (
        "w = sorted(xs, key=lambda x: f(x))\n"
        "k = lambda x: x.lower\n"
        "m = lambda a, b: g(b, a)\n"
        "n = mapper(lambda p: ns.fn(p))\n"
    )
    out = _apply(src)
    assert out is not None
    ast.parse(out)


def test_semantic_equality_of_rewrite():
    # The rewritten callable behaves identically to the wrapping lambda.
    def f(v):
        return v * 3

    ns = {"f": f}
    before = eval("lambda x: f(x)", ns)  # noqa: S307 - test-controlled input
    src = "g = lambda x: f(x)\n"
    out = _apply(src)
    assert out == "g = f\n"
    exec(compile(out, "m.py", "exec"), ns)  # noqa: S102 - test-controlled input
    after = ns["g"]
    for sample in (0, 1, -2, 7):
        assert before(sample) == after(sample)
