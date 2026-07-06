"""Apex native intelligence (v0) — learn-from-the-project stub synthesis.

Pins the deterministic, zero-token, offline behaviour: it mines the project's own
functions into candidate bodies, adapts them to a stub's params, and PROPOSES them
— every proposal still gated by ``stub_synthesis``'s never-fake-green verifier, so
nothing lands unverified.
"""

from __future__ import annotations

from app.engine.native_synth import (
    adapt_expr_to_params,
    learn_return_exemplars,
    mind_candidate_exprs,
)
from app.execution.stub_synthesis import find_stub_functions, verify_body_via_doctest


# --- learning from the corpus ------------------------------------------------

def test_learns_single_return_exemplars():
    ex = learn_return_exemplars([
        "def add(a, b):\n    return a + b\n",
        "def shout(s):\n    return s.upper()\n",
    ])
    got = {(e.name, e.params, e.expr) for e in ex}
    assert ("add", ("a", "b"), "a + b") in got
    assert ("shout", ("s",), "s.upper()") in got


def test_drops_free_name_and_varargs_and_bare_return():
    ex = learn_return_exemplars([
        "def freeref(a):\n    return a + GLOBAL\n",        # free name (GLOBAL)
        "def variadic(*args):\n    return sum(args)\n",    # varargs
        "def bare(a):\n    return\n",                       # bare return
    ])
    assert ex == []


def test_single_temp_then_return_is_now_a_learned_fourth_shape():
    # A one-assignment-then-return body is the FOURTH finishable shape (see
    # tests/test_native_synth_inline_temps_eyml.py for the full inlined-temps
    # pattern space) -> the temp is inlined into the return, no longer declined.
    ex = learn_return_exemplars(["def multi(a):\n    x = a + 1\n    return x\n"])
    assert [(e.name, e.expr) for e in ex] == [("multi", "a + 1")]


def test_docstring_is_skipped_before_single_return():
    ex = learn_return_exemplars([
        'def area(w, h):\n    """Area."""\n    return w * h\n',
    ])
    assert [(e.name, e.expr) for e in ex] == [("area", "w * h")]


def test_learning_is_deterministic_and_sorted():
    corpus = ["def z(a):\n    return a\n", "def a2(a, b):\n    return a + b\n"]
    assert learn_return_exemplars(corpus) == learn_return_exemplars(corpus)
    # Sorted by (arity, name, expr): the 1-arg `z` precedes the 2-arg `a2`.
    names = [e.name for e in learn_return_exemplars(corpus)]
    assert names == ["z", "a2"]


# --- adapting an exemplar onto a stub's params -------------------------------

def test_adapt_remaps_params_positionally():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("x", "y")) == "x + y"


def test_adapt_identity_when_names_match():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("a", "b")) == "a + b"


def test_adapt_none_on_arity_mismatch():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("x",)) is None


def test_adapt_only_touches_param_loads():
    # `s` is a param → remapped; `.upper` (an attribute) is untouched.
    assert adapt_expr_to_params(("s",), "s.upper()", ("t",)) == "t.upper()"


# --- ranked candidate proposals ----------------------------------------------

def test_candidates_are_labelled_deduped_and_deterministic():
    corpus = ["def add(a, b):\n    return a + b\n",
              "def plus(m, n):\n    return m + n\n"]  # same shape → one candidate
    c1 = mind_candidate_exprs(corpus, ("x", "y"))
    c2 = mind_candidate_exprs(corpus, ("x", "y"))
    assert c1 == c2                       # deterministic
    exprs = [expr for _, expr in c1]
    assert exprs == ["x + y"]             # de-duplicated to the one adapted body
    assert all(label.startswith("native-mind:") for label, _ in c1)  # honest label


# --- end-to-end: propose, then the EXISTING gate disposes --------------------

def test_lands_a_stub_only_through_the_verifier():
    corpus = ["def add(a, b):\n    return a + b\n",
              "def area(w, h):\n    return w * h\n"]
    stub_src = ('def total(x, y):\n    """Sum.\n\n    >>> total(2, 3)\n    5\n'
                '    >>> total(10, 4)\n    14\n    """\n    raise NotImplementedError\n')
    stub = find_stub_functions(stub_src)[0]

    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = (label, expr)
            break

    assert landed == ("native-mind:add", "x + y")  # x*y is proposed but fails the gate


def test_wrong_proposals_are_rejected_by_the_gate():
    # A corpus with only a WRONG-shape body must land NOTHING (never fake green).
    corpus = ["def area(w, h):\n    return w * h\n"]
    stub_src = ('def total(x, y):\n    """Sum.\n\n    >>> total(2, 3)\n    5\n    """\n'
                "    raise NotImplementedError\n")
    stub = find_stub_functions(stub_src)[0]
    landed = [
        (label, expr) for label, expr in mind_candidate_exprs(corpus, stub.params)
        if verify_body_via_doctest(stub_src, stub, expr)
    ]
    assert landed == []  # x*y != sum → gate refuses → nothing lands
