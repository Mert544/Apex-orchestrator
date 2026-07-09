"""Native intelligence (v0) — SELF-CONTAINED comprehension/generator return
bodies, learned with SCOPE awareness.

Before this module, ``_expr_uses_only`` rejected ANY comprehension or generator
expression outright (via ``_BINDING_NODES``), so ubiquitous real return bodies —
``return [x * 2 for x in items]``, ``return {k: v for k, v in pairs}``,
``return sum(f(i) for i in a)`` — were 100% invisible to the native mind. This
capability makes them learnable when (and only when) they are still
SELF-CONTAINED: a comprehension's own loop-var names are tracked as locally
bound (not free), so ``[x * 2 for x in a]`` (over param ``a`` only) is learned,
while ``[g(x) for x in a]`` (a genuinely free ``g``) still is not. Walrus,
lambda, ``yield``/``await`` stay refused outright — this is a SCOPE-CORRECT
widening, never a laxer one.

A second, correctness-critical guard (:func:`_body_binds_a_stub_param`) refuses
to PROPOSE (never even offers to the gate) an adaptation where a stub's own
param name collides with a comprehension's loop-var name — such a remap would
silently shadow the substituted param inside the comprehension body, producing
a corrupted expression rather than merely a wrong one.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from app.engine.native_synth import (
    _body_binds_a_stub_param,
    _comprehension_bound_names,
    _expr_uses_only,
    learn_return_exemplars,
    mind_candidate_exprs,
)
from app.execution.stub_synthesis import (
    _native_mind_sources,
    _ordered_candidates,
    find_stub_functions,
    synthesize_expr_from_witnesses,
    verify_body_via_doctest,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


# --- learning self-contained comprehension/generator shapes ------------------

def test_learns_a_list_comprehension():
    ex = learn_return_exemplars(["def dbl(a):\n    return [x * 2 for x in a]\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("dbl", ("a",), "[x * 2 for x in a]")]


def test_learns_a_dict_comprehension():
    ex = learn_return_exemplars(["def ident_map(a):\n    return {k: k for k in a}\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("ident_map", ("a",), "{k: k for k in a}")]


def test_learns_a_genexpr_over_a_safe_builtin():
    # ast.unparse renders the sole genexpr argument with explicit parens.
    ex = learn_return_exemplars(["def total(a):\n    return sum(x for x in a)\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("total", ("a",), "sum((x for x in a))")]


def test_learns_a_two_param_comprehension():
    ex = learn_return_exemplars(["def combine(a, b):\n    return [a + x for x in b]\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("combine", ("a", "b"), "[a + x for x in b]")]


def test_learns_a_nested_comprehension():
    # Two `for` clauses in one comprehension (a flatten) — every loop-var
    # (`x` AND `y`) is scope-tracked, so only the free param `a` is checked.
    ex = learn_return_exemplars(
        ["def flat(a):\n    return [y for x in a for y in x]\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("flat", ("a",), "[y for x in a for y in x]")]


def test_learns_a_comprehension_with_an_if():
    ex = learn_return_exemplars(["def truthy(a):\n    return [x for x in a if x]\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("truthy", ("a",), "[x for x in a if x]")]


# --- rejections: still declined, for the right reason ------------------------

def test_free_global_in_the_comprehension_body_is_not_learned():
    ex = learn_return_exemplars(["def leaky(a):\n    return [g(x) for x in a]\n"])
    assert ex == []


def test_free_global_in_the_comprehension_iterable_is_not_learned():
    ex = learn_return_exemplars(["def leaky(a):\n    return [x for x in GLOBAL]\n"])
    assert ex == []


def test_walrus_inside_a_comprehension_is_not_learned():
    ex = learn_return_exemplars(["def w(a):\n    return [(z := x) for x in a]\n"])
    assert ex == []


def test_lambda_inside_a_comprehension_is_not_learned():
    ex = learn_return_exemplars(["def l(a):\n    return [(lambda: x) for x in a]\n"])
    assert ex == []


def test_genexpr_calling_a_non_safe_builtin_is_not_learned():
    # `any` is not in the safe-builtins allowlist -> a free name, not learned.
    ex = learn_return_exemplars(["def anyof(a):\n    return any(x for x in a)\n"])
    assert ex == []


# --- the adaptation-collision guard ------------------------------------------

def test_stub_param_colliding_with_a_loop_var_yields_no_candidate():
    # `[a + x for x in a]` (param `a`) adapted onto a stub whose OWN param is
    # named `x` would naively become `[x + x for x in x]` (both reads now see
    # the loop var, never the substituted param) — dropped, not proposed.
    corpus = ["def f(a):\n    return [a + x for x in a]\n"]
    assert mind_candidate_exprs(corpus, ("x",)) == []


def test_stub_param_with_no_loop_var_collision_adapts_cleanly():
    corpus = ["def f(a):\n    return [a + x for x in a]\n"]
    assert mind_candidate_exprs(corpus, ("q",)) == [
        ("native-mind:f", "[q + x for x in q]")]


def test_body_binds_a_stub_param_predicate_directly():
    assert _body_binds_a_stub_param("[a + x for x in a]", ("x",)) is True
    assert _body_binds_a_stub_param("[a + x for x in a]", ("q",)) is False
    # No comprehension at all -> nothing bound, never fires.
    assert _body_binds_a_stub_param("a + b", ("a", "b")) is False
    # Unparseable expression -> conservative drop.
    assert _body_binds_a_stub_param("not an expr (", ("a",)) is True


def test_comprehension_bound_names_handles_tuple_targets_and_nesting():
    tree = ast.parse("{k: v for k, v in pairs}", mode="eval")
    assert _comprehension_bound_names(tree) == {"k", "v"}
    nested_tree = ast.parse("[[y for y in x] for x in a]", mode="eval")
    assert _comprehension_bound_names(nested_tree) == {"x", "y"}
    list_target_tree = ast.parse("[c for [a, b], c in triples]", mode="eval")
    assert _comprehension_bound_names(list_target_tree) == {"a", "b", "c"}


# --- regression: the 4 prior finishable shapes stay byte-identical ----------

def test_regression_single_return_shape_unchanged():
    ex = learn_return_exemplars(["def add(a, b):\n    return a + b\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [("add", ("a", "b"), "a + b")]


def test_regression_guarded_return_shape_unchanged():
    ex = learn_return_exemplars(
        ["def clamplo(x, lo):\n    if x < lo:\n        return lo\n    return x\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("clamplo", ("x", "lo"), "lo if x < lo else x")]


def test_regression_elif_chain_shape_unchanged():
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return b\n    return a\n",
    ])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("t", ("a", "b"), "a if a > b else b if a == b else a")]


def test_regression_inlined_temps_shape_unchanged():
    ex = learn_return_exemplars(["def multi(a):\n    x = a + 1\n    return x\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [("multi", ("a",), "a + 1")]


def test_regression_bare_free_name_still_rejected():
    assert _expr_uses_only("a + GLOBAL", {"a"}) is False


def test_regression_walrus_in_a_non_comp_expr_still_rejected():
    assert _expr_uses_only("(z := a)", {"a"}) is False


def test_regression_lambda_in_a_non_comp_expr_still_rejected():
    assert _expr_uses_only("lambda: a", {"a"}) is False


def test_regression_plain_param_expr_still_accepted():
    assert _expr_uses_only("a.upper()", {"a"}) is True


# --- determinism --------------------------------------------------------------

def test_learning_comprehensions_is_deterministic():
    corpus = [
        "def dbl(a):\n    return [x * 2 for x in a]\n",
        "def combine(a, b):\n    return [a + x for x in b]\n",
    ]
    first = learn_return_exemplars(corpus)
    for _ in range(5):
        assert learn_return_exemplars(corpus) == first


def test_candidates_are_deterministic():
    corpus = ["def dbl(a):\n    return [x * 2 for x in a]\n"]
    first = mind_candidate_exprs(corpus, ("q",))
    for _ in range(5):
        assert mind_candidate_exprs(corpus, ("q",)) == first


# --- end-to-end: propose via mind_candidate_exprs, gate disposes -------------

def test_comprehension_candidate_lands_through_the_doctest_gate():
    corpus = ["def dbl(a):\n    return [x * 2 for x in a]\n"]
    stub_src = ('def doubleall(vals):\n    """Double each.\n\n'
                '    >>> doubleall([1, 2, 3])\n    [2, 4, 6]\n'
                '    >>> doubleall([])\n    []\n    """\n'
                "    raise NotImplementedError\n")
    stub = find_stub_functions(stub_src)[0]
    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = (label, expr)
            break
    assert landed == ("native-mind:dbl", "[x * 2 for x in vals]")


def test_wrong_comprehension_candidate_is_refused_by_the_gate():
    # A learned SQUARE body must not land onto a DOUBLE contract.
    corpus = ["def sq(a):\n    return [x * x for x in a]\n"]
    stub_src = ('def doubleall(vals):\n    """Double each.\n\n'
                '    >>> doubleall([1, 2, 3])\n    [2, 4, 6]\n    """\n'
                "    raise NotImplementedError\n")
    stub = find_stub_functions(stub_src)[0]
    landed = [
        (label, expr) for label, expr in mind_candidate_exprs(corpus, stub.params)
        if verify_body_via_doctest(stub_src, stub, expr)
    ]
    assert landed == []


# --- end-to-end via the real APEX_NATIVE_MIND wire-in ------------------------

@pytest.fixture(autouse=True)
def _clean_native_cache():
    _native_mind_sources.cache_clear()
    yield
    _native_mind_sources.cache_clear()


def test_comprehension_is_wired_into_the_real_candidate_path(tmp_path, monkeypatch):
    """A project-mined nested comprehension (a FLATTEN, which no fixed template
    covers) surfaces as a native-mind candidate through the SAME
    ``_ordered_candidates`` path ``synthesize_expr_from_witnesses`` uses. Absent
    with the lane off; present with it on."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py",
           "def flat(a):\n    return [y for x in a for y in x]\n")
    _write(tmp_path, "pkg/flatten.py", "def flatten(a):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_flatten.py", """
        from pkg.flatten import flatten

        def test_flat():
            assert flatten([[1, 2], [3], []]) == [1, 2, 3]

        def test_single():
            assert flatten([[9]]) == [9]
        """)
    src = (tmp_path / "pkg" / "flatten.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]
    assert stub.params == ("a",)

    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()
    off = _ordered_candidates(tmp_path, ["tests/test_flatten.py"], stub)
    assert all(not label.startswith("native-mind:") for label, _ in off)

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    on = _ordered_candidates(tmp_path, ["tests/test_flatten.py"], stub)
    assert ("native-mind:flat", "[y for x in a for y in x]") in on


def test_comprehension_lands_end_to_end_through_synthesize_expr_from_witnesses(
        tmp_path, monkeypatch):
    """Proves the in-process eval sandbox (``_expr_matches_all``) evaluates a
    learned comprehension candidate identically to the pytest apply: OFF, the
    flatten stub is unsynthesizable (no fixed template flattens a list of
    lists) so Apex refuses; ON, the learned nested-comprehension body verifies
    against every pinned witness and lands, through the exact same
    ``synthesize_expr_from_witnesses`` entry point ``implement-stub`` uses."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py",
           "def flat(a):\n    return [y for x in a for y in x]\n")
    _write(tmp_path, "pkg/flatten.py", "def flatten(a):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_flatten.py", """
        from pkg.flatten import flatten

        def test_flat():
            assert flatten([[1, 2], [3], []]) == [1, 2, 3]

        def test_single():
            assert flatten([[9]]) == [9]
        """)
    src = (tmp_path / "pkg" / "flatten.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]

    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_flatten.py"], stub) is None

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_flatten.py"], stub) == "[y for x in a for y in x]"


def test_wrong_learned_comprehension_is_refused_by_the_gate_end_to_end(
        tmp_path, monkeypatch):
    """A learned comprehension that does NOT satisfy the stub's tests lands
    NOTHING even with the lane on — never-fake-green holds through the wire-in."""
    _write(tmp_path, "pkg/__init__.py", "")
    # The only exemplar SQUARES elements — wrong for a doubling contract.
    _write(tmp_path, "pkg/lib.py", "def sq(a):\n    return [x * x for x in a]\n")
    _write(tmp_path, "pkg/doubleall.py",
           "def doubleall(a):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_doubleall.py", """
        from pkg.doubleall import doubleall

        def test_basic():
            assert doubleall([1, 2, 3]) == [2, 4, 6]
        """)
    src = (tmp_path / "pkg" / "doubleall.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_doubleall.py"], stub) is None


# --- adversarial-review regressions (scope soundness + capture-avoidance) ------
# Four defects an adversarial pass confirmed could land/mis-handle a body; each
# is fixed at the root here and pinned below.

def test_self_shadowing_exemplar_is_not_learned():
    # HIGH: `[s * 2 for s in s]` — the param `s` is ALSO the comp loop-var, so a
    # transplant rename would corrupt the body (it renames the loop-var reads
    # Python resolves to the comprehension's own scope). Never learned.
    assert learn_return_exemplars(["def f(s):\n    return [s * 2 for s in s]\n"]) == []
    # ...and therefore never proposed for any stub.
    assert mind_candidate_exprs(
        ["def f(s):\n    return [s * 2 for s in s]\n"], ("t",)) == []


def test_free_name_that_is_also_a_loop_var_elsewhere_is_rejected():
    # HIGH: scope-imprecision bypass — `x` is a comp target in one place AND a
    # genuine free reference in the trailing `+ x`. Scope-correct free-name
    # analysis must still catch the free `x` (a whole-tree bound-union would not).
    assert _expr_uses_only("[x for x in a] + x", {"a"}) is False
    assert learn_return_exemplars(["def f(a):\n    return [x for x in a] + x\n"]) == []
    # a free name used only INSIDE the comprehension is likewise still refused
    assert _expr_uses_only("[g(x) for x in a]", {"a"}) is False


def test_starred_comprehension_target_is_bound_not_free():
    # LOW: `for a, *rest in pairs` binds BOTH `a` and `rest`; a self-contained
    # body using `rest` must be learnable (was wrongly rejected as free).
    ex = learn_return_exemplars(["def f(p):\n    return [rest for a, *rest in p]\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "[rest for a, *rest in p]")]
    assert _comprehension_bound_names(
        ast.parse("[rest for a, *rest in p]", mode="eval")) == {"a", "rest"}


def test_comprehension_candidate_is_verifiable_in_process():
    # MEDIUM (scan/apply parity): a comprehension whose param appears INSIDE the
    # body (not just as the outer iterable) must verify in the in-process sandbox
    # exactly as the pytest apply would — params are evaluated as globals so the
    # comprehension's nested scope can see them.
    from types import SimpleNamespace

    from app.execution.stub_synthesis import _expr_matches_all
    stub = SimpleNamespace(params=("a", "b"))
    assert _expr_matches_all("[a + x for x in b]", stub,
                             [((1, [10, 20]), [11, 21]), ((5, [0]), [5])]) is True
    # a wrong comprehension body still fails the in-process check (fails closed)
    assert _expr_matches_all("[a - x for x in b]", stub, [((1, [10]), [11])]) is False
    # plain expressions stay byte-identical under the globals-eval
    assert _expr_matches_all("a + b", stub, [((2, 3), 5), ((10, 1), 11)]) is True
