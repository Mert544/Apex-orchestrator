"""Native intelligence (v0) — the FOURTH finishable body shape: INLINED TEMPS.

Beyond a plain ``return <expr>``, a two-branch guarded return, and an elif
chain, the native intelligence now learns a body that is a short run of
SINGLE-USE local assignments ending in a ``return`` — every temp inlined into
the return so the whole body collapses to ONE self-contained expression:

* ``r = a + 1; return r``                -> ``a + 1``
* ``s = a + b; return s * 2``            -> ``(a + b) * 2``
* ``x = a + 1; y = x * 2; return y``     -> ``(a + 1) * 2``  (chained)

This grows the learnable corpus substantially (real functions constantly use a
temp), so the zero-token native-mind lane can finish strictly MORE real stubs.
These tests pin the new shape, its boundaries (what stays UN-learnable), and
prove the THREE prior shapes stay byte-identical.
"""

from __future__ import annotations

import pytest

from app.engine.native_synth import learn_return_exemplars, mind_candidate_exprs
from app.execution.stub_synthesis import (
    _native_mind_sources,
    find_stub_functions,
    synthesize_expr_from_witnesses,
    verify_body_via_doctest,
)


# --- learning the inlined-temps shape ------------------------------------------

def test_single_temp_is_inlined():
    ex = learn_return_exemplars(["def f(a):\n    r = a + 1\n    return r\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "a + 1")]


def test_temp_used_in_a_richer_return_expression():
    ex = learn_return_exemplars(["def f(a, b):\n    s = a + b\n    return s * 2\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "(a + b) * 2")]


def test_two_chained_temps_fold_in_order():
    ex = learn_return_exemplars([
        "def f(a):\n    x = a + 1\n    y = x * 2\n    return y\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [("f", "(a + 1) * 2")]


def test_three_chained_temps_fold_in_order():
    ex = learn_return_exemplars([
        "def f(a):\n    x = a + 1\n    y = x * 2\n    z = y - 1\n    return z\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [("f", "(a + 1) * 2 - 1")]


def test_temp_used_twice_in_the_return_is_duplicated_not_forbidden():
    # Multi-use of a PURE sub-expression is semantically identical to inlining it
    # once per use -> allowed. (An IMPURE method-call RHS used twice is NOT — see
    # test_duplicated_method_call_is_declined below, which the _method_call_count
    # guard refuses because the gate cannot prove `a.pop()` side-effect-free.)
    ex = learn_return_exemplars(["def f(a):\n    r = a + 1\n    return r + r\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "a + 1 + (a + 1)")]


def test_builtin_call_duplication_stays_allowed():
    # A bare safe-builtin call (Name func) is pure -> duplicating it is safe, so
    # the guard (which counts only METHOD calls) leaves it learnable.
    ex = learn_return_exemplars(["def f(a):\n    r = len(a)\n    return r + r\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "len(a) + len(a)")]


def test_single_method_call_temp_stays_learnable():
    # ONE method call, used once -> no duplication, no reordering -> safe to
    # inline (only >1 surviving method call is refused).
    ex = learn_return_exemplars(["def f(a):\n    r = a.strip()\n    return r\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "a.strip()")]


def test_duplicated_method_call_is_declined():
    # r = a.pop(); return r + r  would fold to `a.pop() + a.pop()` — TWO pops
    # where the source pops ONCE. The gate admits method calls but cannot prove
    # them pure, so inlining refuses to DUPLICATE one (corpus-fidelity + a
    # confirmed landing-safety bug on a thin oracle). Declined outright.
    ex = learn_return_exemplars(["def f(a):\n    r = a.pop()\n    return r + r\n"])
    assert ex == []


def test_reordered_method_calls_are_declined():
    # x = a.pop(); y = a.pop(); return y - x  would fold to `a.pop() - a.pop()`,
    # reordering which physical pop feeds which slot. Two surviving method calls
    # -> refused.
    ex = learn_return_exemplars([
        "def f(a):\n    x = a.pop()\n    y = a.pop()\n    return y - x\n"])
    assert ex == []


def test_yield_and_await_in_an_rhs_are_declined():
    # A yield/await RHS turns the spliced function into a generator/coroutine — a
    # different return protocol. `(yield a)` even parses in mode="eval" on some
    # CPythons, so _BINDING_NODES must reject Yield/YieldFrom/Await explicitly.
    assert learn_return_exemplars(
        ["def f(a):\n    r = (yield a)\n    return r\n"]) == []
    assert learn_return_exemplars(
        ["async def f(a):\n    r = await a\n    return r\n"]) == []
    assert learn_return_exemplars(
        ["def f(a):\n    r = (yield from a)\n    return r\n"]) == []


def test_docstring_then_temps_then_return():
    ex = learn_return_exemplars([
        'def f(a):\n    """doc"""\n    r = a + 1\n    return r\n',
    ])
    assert [(e.name, e.expr) for e in ex] == [("f", "a + 1")]


# --- boundaries: what stays UN-learnable --------------------------------------

def test_reassigned_temp_is_not_learned():
    # `r` assigned twice -> not a clean single-use temp -> declined.
    ex = learn_return_exemplars([
        "def f(a, b):\n    r = a\n    r = b\n    return r\n",
    ])
    assert ex == []


def test_augmented_assign_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a):\n    r = 0\n    r += a\n    return r\n",
    ])
    assert ex == []


def test_tuple_unpack_target_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a, b):\n    x, y = a, b\n    return x\n",
    ])
    assert ex == []


def test_attribute_target_is_not_learned():
    ex = learn_return_exemplars([
        "class C:\n    def f(self, a):\n        self.x = a\n        return self.x\n",
    ])
    assert ex == []


def test_subscript_target_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a):\n    d = {}\n    d[0] = a\n    return d\n",
    ])
    assert ex == []


def test_free_name_in_a_temp_rhs_is_rejected_by_the_self_contained_gate():
    # `GLOBAL` is not a param -> the inlined expression ("a + GLOBAL") fails
    # `_expr_uses_only` in the caller, exactly like the other three shapes.
    ex = learn_return_exemplars([
        "def f(a):\n    r = a + GLOBAL\n    return r\n",
    ])
    assert ex == []


def test_if_statement_among_the_assignments_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a, b):\n    if a:\n        r = a\n    else:\n        r = b\n    return r\n",
    ])
    assert ex == []


def test_for_statement_among_the_assignments_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a):\n    total = 0\n    for x in a:\n        total = total + x\n"
        "    return total\n",
    ])
    assert ex == []


def test_bare_return_is_not_learned():
    ex = learn_return_exemplars(["def f(a):\n    r = a\n    return\n"])
    assert ex == []


def test_two_returns_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a):\n    r = a\n    return r\n    return a\n",
    ])
    assert ex == []


def test_param_reassignment_is_not_learned():
    # `a = a + 1` mutates the parameter itself -> too subtle to safely inline.
    ex = learn_return_exemplars(["def f(a):\n    a = a + 1\n    return a\n"])
    assert ex == []


def test_yield_body_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a):\n    r = a\n    yield r\n    return r\n",
    ])
    assert ex == []


def test_expression_statement_among_assignments_is_not_learned():
    ex = learn_return_exemplars([
        "def f(a):\n    r = a\n    print(r)\n    return r\n",
    ])
    assert ex == []


# --- REGRESSION: the three prior shapes stay byte-identical -------------------

def test_regression_single_return_exemplar_unchanged():
    ex = learn_return_exemplars(["def add(a, b):\n    return a + b\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("add", ("a", "b"), "a + b")]


def test_regression_guarded_fallthrough_exemplar_unchanged():
    ex = learn_return_exemplars([
        "def clamplo(x, lo):\n    if x < lo:\n        return lo\n    return x\n",
    ])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("clamplo", ("x", "lo"), "lo if x < lo else x")]


def test_regression_guarded_if_else_exemplar_unchanged():
    ex = learn_return_exemplars([
        "def pick(a, b):\n    if a > b:\n        return a\n    else:\n        return b\n",
    ])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("pick", ("a", "b"), "a if a > b else b")]


def test_regression_elif_chain_exemplar_unchanged():
    ex = learn_return_exemplars([
        "def sign_cmp(a, b):\n    if a > b:\n        return 1\n    elif a < b:\n"
        "        return -1\n    else:\n        return 0\n",
    ])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("sign_cmp", ("a", "b"), "1 if a > b else -1 if a < b else 0")]


# --- determinism ---------------------------------------------------------------

def test_learning_inlined_temps_is_deterministic():
    corpus = [
        "def f(a):\n    x = a + 1\n    y = x * 2\n    return y\n",
        "def add(a, b):\n    return a + b\n",
        "def pick(a, b):\n    if a > b:\n        return a\n    else:\n        return b\n",
    ]
    first = learn_return_exemplars(corpus)
    for _ in range(5):
        assert learn_return_exemplars(corpus) == first


# --- end-to-end: proposed, then the EXISTING gate disposes --------------------

def test_inlined_temps_exemplar_adapts_and_lands_through_the_gate():
    corpus = ["def scale(a, b):\n    s = a + b\n    return s * 2\n"]
    stub_src = (
        'def combine(x, y):\n    """Combine.\n\n    >>> combine(1, 2)\n    6\n'
        '    >>> combine(3, 4)\n    14\n    """\n    raise NotImplementedError\n'
    )
    stub = find_stub_functions(stub_src)[0]
    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = (label, expr)
            break
    assert landed == ("native-mind:scale", "(x + y) * 2")


def test_inlined_temps_wrong_shape_is_refused_by_the_gate():
    corpus = ["def scale(a, b):\n    s = a + b\n    return s * 2\n"]
    # Contract wants the SUM, not (x + y) * 2 -> the learned body is refused.
    stub_src = (
        'def total(x, y):\n    """Sum.\n\n    >>> total(2, 3)\n    5\n'
        '    >>> total(10, 4)\n    14\n    """\n    raise NotImplementedError\n'
    )
    stub = find_stub_functions(stub_src)[0]
    landed = [
        (label, expr) for label, expr in mind_candidate_exprs(corpus, stub.params)
        if verify_body_via_doctest(stub_src, stub, expr)
    ]
    assert landed == []


# --- end-to-end via the real wire-in path (opt-in APEX_NATIVE_MIND lane) ------

@pytest.fixture(autouse=True)
def _clean_native_cache():
    _native_mind_sources.cache_clear()
    yield
    _native_mind_sources.cache_clear()


def test_chained_temps_transplant_through_stub_synthesis_wire_in(tmp_path, monkeypatch):
    """A stub whose intended body is ``(a + 1) * 2`` is finished ONLY via the
    native-mind lane, transplanting the project's own chained-temp exemplar."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "lib.py").write_text(
        "def bump_double(a):\n    x = a + 1\n    y = x * 2\n    return y\n",
        encoding="utf-8",
    )
    stub_src = (
        'def grow(n):\n    """Grow.\n\n    >>> grow(1)\n    4\n    >>> grow(3)\n'
        '    8\n    """\n    raise NotImplementedError\n'
    )
    (tmp_path / "pkg" / "grow.py").write_text(stub_src, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_grow.py").write_text(
        "from pkg.grow import grow\n\n\n"
        "def test_one():\n    assert grow(1) == 4\n\n\n"
        "def test_three():\n    assert grow(3) == 8\n",
        encoding="utf-8",
    )
    src = (tmp_path / "pkg" / "grow.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]

    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_grow.py"], stub) is None  # no template fits

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_grow.py"], stub) == "(n + 1) * 2"
