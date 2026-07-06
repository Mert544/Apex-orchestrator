"""Native intelligence (v0) — expanded pattern space: two-branch GUARDED returns.

Beyond a plain ``return <expr>``, the native intelligence now learns the common
guarded-return shape (``if T: return A; return B`` and its if/else twin) as the
equivalent ternary ``A if T else B`` — a single expression it can transplant with
the same positional remap and the same never-fake-green gate. These tests pin the
new shapes AND the boundaries (what stays UN-learnable), so the pattern space can
grow without ever loosening the self-contained (params-only) rule.
"""

from __future__ import annotations

from app.engine.native_synth import (
    learn_return_exemplars,
    mind_candidate_exprs,
)
from app.execution.stub_synthesis import find_stub_functions, verify_body_via_doctest


def test_learns_guard_then_fallthrough():
    ex = learn_return_exemplars([
        "def clamplo(x, lo):\n    if x < lo:\n        return lo\n    return x\n",
    ])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("clamplo", ("x", "lo"), "lo if x < lo else x")]


def test_learns_if_else_both_return():
    ex = learn_return_exemplars([
        "def pick(a, b):\n    if a > b:\n        return a\n    else:\n        return b\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [("pick", "a if a > b else b")]


def test_guarded_docstring_is_skipped():
    ex = learn_return_exemplars([
        'def hi(n, z):\n    """doc"""\n    if n > z:\n        return n\n    return z\n',
    ])
    assert [(e.name, e.expr) for e in ex] == [("hi", "n if n > z else z")]


def test_elif_chain_is_not_learned():
    # A three-branch body is NOT one of the two clean shapes -> declined.
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return b\n    return a\n",
    ])
    assert ex == []


def test_free_name_in_a_branch_is_not_learned():
    # A branch that reads a global is not self-contained -> declined (no transplant).
    ex = learn_return_exemplars([
        "def leaky(a, b):\n    if a > b:\n        return GLOBAL\n    return b\n",
    ])
    assert ex == []


def test_bare_return_branch_is_not_learned():
    # `return` with no value cannot become a ternary arm -> declined.
    ex = learn_return_exemplars([
        "def maybe(a, b):\n    if a > b:\n        return\n    return b\n",
    ])
    assert ex == []


def test_statement_after_the_guard_is_not_learned():
    # An assignment between the guard and the fallthrough is not a clean 2-branch
    # shape (len(body) != 2) -> declined.
    ex = learn_return_exemplars([
        "def busy(a, b):\n    if a > b:\n        return a\n    c = b\n    return c\n",
    ])
    assert ex == []


def test_guarded_exemplar_adapts_and_lands_through_the_gate():
    # A stub whose pinned doctest describes a max(a,b) via clamp/pick shape: the
    # learned guarded body adapts to the stub params and passes the SAME verifier.
    corpus = ["def pick(a, b):\n    if a > b:\n        return a\n    else:\n        return b\n"]
    stub_src = ('def bigger(x, y):\n    """Bigger.\n\n    >>> bigger(3, 5)\n    5\n'
                '    >>> bigger(9, 2)\n    9\n    """\n    raise NotImplementedError\n')
    stub = find_stub_functions(stub_src)[0]
    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = (label, expr)
            break
    assert landed == ("native-mind:pick", "x if x > y else y")


def test_dominant_idiom_is_ranked_first():
    # Three of the project's functions subtract, one adds -> subtraction is the
    # dominant idiom, so the native intelligence proposes it FIRST.
    corpus = [
        "def a1(a, b):\n    return a - b\n",
        "def a2(m, n):\n    return m - n\n",
        "def a3(p, q):\n    return p - q\n",
        "def a4(x, y):\n    return x + y\n",
    ]
    ranked = [expr for _label, expr in mind_candidate_exprs(corpus, ("u", "v"))]
    assert ranked == ["u - v", "u + v"]


def test_frequency_ties_break_on_stable_exemplar_order():
    # Two idioms, one function each -> a deterministic tie broken by the exemplar
    # sort (arity, name, expr): `add` (a+b) precedes `sub` (a-b).
    corpus = [
        "def sub(a, b):\n    return a - b\n",
        "def add(a, b):\n    return a + b\n",
    ]
    labels = [label for label, _ in mind_candidate_exprs(corpus, ("x", "y"))]
    assert labels == ["native-mind:add", "native-mind:sub"]


def test_ranking_does_not_change_what_the_gate_lands():
    # Even though `x - y` outranks `x + y`, a SUM contract still lands `x + y`:
    # ranking only reorders proposals; the gate decides correctness.
    corpus = [
        "def a1(a, b):\n    return a - b\n",
        "def a2(m, n):\n    return m - n\n",
        "def a3(p, q):\n    return p + q\n",
    ]
    stub_src = ('def total(x, y):\n    """Sum.\n\n    >>> total(2, 3)\n    5\n'
                '    >>> total(10, 4)\n    14\n    """\n    raise NotImplementedError\n')
    stub = find_stub_functions(stub_src)[0]
    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = expr
            break
    assert landed == "x + y"  # x - y is tried first, refused; x + y verifies


def test_guarded_wrong_shape_is_refused_by_the_gate():
    # A learned guard that does NOT satisfy the stub's examples lands nothing.
    corpus = ["def pick(a, b):\n    if a > b:\n        return a\n    else:\n        return b\n"]
    # Contract is MIN, not max -> the learned max body must be refused.
    stub_src = ('def smaller(x, y):\n    """Smaller.\n\n    >>> smaller(3, 5)\n    3\n'
                '    >>> smaller(9, 2)\n    2\n    """\n    raise NotImplementedError\n')
    stub = find_stub_functions(stub_src)[0]
    landed = [
        (label, expr) for label, expr in mind_candidate_exprs(corpus, stub.params)
        if verify_body_via_doctest(stub_src, stub, expr)
    ]
    assert landed == []
