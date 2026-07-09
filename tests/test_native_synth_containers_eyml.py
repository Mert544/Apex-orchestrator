"""Native intelligence (v0) — literal-container return bodies (dict/list/tuple
builders): the purity/depth/key GATE, plain AND guarded.

HONEST FRAMING (verified empirically during integration): container-literal
bodies — ``return {"x": a, "y": b}`` / ``return [a, b]`` / ``return (a, b)`` —
were ALWAYS learnable through the generic single-return path; nothing here
adds a new shape. What this capability adds is the previously-missing
DISCIPLINE on that surface: a learned container body must now have every
element pass ``_expr_uses_only`` (as before), nesting at most depth 2,
constant-only dict keys, and provably PURE elements (zero attribute-calls —
stricter than the inlined-temps ">1" threshold, since no folding step here
already tolerates duplication). Pre-gate, ``return {'x': a.pop()}`` was
learned and transplantable — a receiver-mutating element the doctest canary
can be fooled by across evals; post-gate it is refused at learn time. The
guarded variant needs no new machinery: the gate walks the FINAL expression,
so a container inside a guarded/elif body is policed identically.

These tests pin the pre-existing learnability (regression), the gate's exact
boundaries (what becomes UN-learnable), that the four prior shapes stay
byte-identical, and that the shared canonical_shape/adapt path needs no
shape-specific changes.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.engine.native_synth import (
    _all_containers_ok,
    _container_depth,
    _container_shape_ok,
    adapt_expr_to_params,
    canonical_shape,
    learn_return_exemplars,
    mind_candidate_exprs,
)
from app.execution.stub_synthesis import (
    _native_mind_sources,
    find_stub_functions,
    verify_body_via_doctest,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


# --- learning the plain literal-container shapes ------------------------------

def test_learns_dict_literal_shape():
    ex = learn_return_exemplars(["def f(a, b):\n    return {'x': a, 'y': b}\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("f", ("a", "b"), "{'x': a, 'y': b}")]


def test_learns_list_literal_shape():
    ex = learn_return_exemplars(["def f(a, b):\n    return [a, b]\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [("f", ("a", "b"), "[a, b]")]


def test_learns_tuple_literal_shape():
    ex = learn_return_exemplars(["def f(a, b):\n    return (a, b)\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [("f", ("a", "b"), "(a, b)")]


def test_learns_nested_container_up_to_depth_2():
    ex = learn_return_exemplars(["def f(a):\n    return {'x': [a]}\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "{'x': [a]}")]


def test_docstring_is_skipped_before_container_literal():
    ex = learn_return_exemplars([
        'def f(a, b):\n    """doc"""\n    return {"x": a, "y": b}\n',
    ])
    assert [(e.name, e.expr) for e in ex] == [("f", "{'x': a, 'y': b}")]


# --- learning the guarded literal-container shape (reuses existing machinery) -

def test_learns_guarded_dict_literal():
    ex = learn_return_exemplars([
        "def f(t, a, b):\n    if t:\n        return {'x': a}\n    return {'x': b}\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [
        ("f", "{'x': a} if t else {'x': b}")]


def test_learns_guarded_list_literal_if_else_form():
    ex = learn_return_exemplars([
        "def f(t, a, b):\n    if t:\n        return [a]\n    else:\n        return [b]\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [("f", "[a] if t else [b]")]


# --- boundaries: what stays UN-learnable --------------------------------------

def test_free_name_in_container_element_rejected():
    ex = learn_return_exemplars(["def f(a):\n    return {'x': a, 'y': GLOBAL}\n"])
    assert ex == []


def test_free_name_in_list_element_rejected():
    ex = learn_return_exemplars(["def f(a):\n    return [a, GLOBAL]\n"])
    assert ex == []


def test_impure_element_rejected():
    # `a.pop()` has ONE method call — the inlined-temps shape would tolerate a
    # single surviving call (>1 threshold), but a container element requires
    # ZERO: no folding step here already tolerates any duplication risk.
    ex = learn_return_exemplars(["def f(a):\n    return {'x': a.pop()}\n"])
    assert ex == []


def test_impure_list_element_rejected():
    ex = learn_return_exemplars(["def f(a):\n    return [a.pop()]\n"])
    assert ex == []


def test_pure_method_call_element_is_still_learned():
    # A method call with proven-zero mutation risk isn't provable either way —
    # the gate is deliberately zero-call, but a bare-builtin (Name func) call is
    # NOT a method call and stays learnable.
    ex = learn_return_exemplars(["def f(a):\n    return {'x': len(a)}\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "{'x': len(a)}")]


def test_depth_3_nesting_refused():
    ex = learn_return_exemplars(["def f(a):\n    return {'x': [[a]]}\n"])
    assert ex == []


def test_depth_2_nesting_is_the_exact_boundary():
    depth2 = learn_return_exemplars(["def f(a):\n    return {'x': [a]}\n"])
    depth3 = learn_return_exemplars(["def f(a):\n    return {'x': [[a]]}\n"])
    assert [(e.expr) for e in depth2] == ["{'x': [a]}"]
    assert depth3 == []


def test_walrus_in_container_rejected():
    ex = learn_return_exemplars(["def f(a):\n    return [(n := a)]\n"])
    assert ex == []


def test_lambda_in_container_rejected():
    ex = learn_return_exemplars(["def f(a):\n    return [lambda: a]\n"])
    assert ex == []


def test_yield_in_container_rejected():
    ex = learn_return_exemplars(["def f(a):\n    return [(yield a)]\n"])
    assert ex == []


def test_non_constant_dict_key_rejected():
    ex = learn_return_exemplars(["def f(a, b):\n    return {a: b}\n"])
    assert ex == []


def test_dict_unpack_key_rejected():
    # `{**a}` has a `None` key entry (unpacking) — not an `ast.Constant`, so
    # this is not the clean `lit_key` shape either.
    ex = learn_return_exemplars(["def f(a):\n    return {**a}\n"])
    assert ex == []


def test_set_literal_is_unaffected_falls_through_unchecked():
    # Sets were never excluded before this capability and the brief doesn't
    # mention them — a set-literal body must stay byte-identical (still learned
    # via the pre-existing generic single-return-expr path, unaffected by the
    # new container gate since ast.Set isn't in _LITERAL_CONTAINER_NODES).
    ex = learn_return_exemplars(["def f(a, b):\n    return {a, b}\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "{a, b}")]


# --- direct unit pins on the new helpers --------------------------------------

def test_container_depth_direct():
    import ast
    assert _container_depth(ast.parse("{'x': a}", mode="eval").body) == 1
    assert _container_depth(ast.parse("{'x': [a]}", mode="eval").body) == 2
    assert _container_depth(ast.parse("{'x': [[a]]}", mode="eval").body) == 3
    assert _container_depth(ast.parse("a", mode="eval").body) == 0


def test_container_shape_ok_direct():
    import ast
    ok = ast.parse("{'x': a}", mode="eval").body
    assert _container_shape_ok(ok) is True
    too_deep = ast.parse("{'x': [[a]]}", mode="eval").body
    assert _container_shape_ok(too_deep) is False
    impure = ast.parse("{'x': a.pop()}", mode="eval").body
    assert _container_shape_ok(impure) is False
    bad_key = ast.parse("{a: 1}", mode="eval").body
    assert _container_shape_ok(bad_key) is False


def test_all_containers_ok_vacuously_true_with_no_container():
    assert _all_containers_ok("a + b") is True
    assert _all_containers_ok("not an expr (") is False


def test_all_containers_ok_walks_into_a_guarded_ternary():
    assert _all_containers_ok("{'x': a} if t else {'x': b}") is True
    assert _all_containers_ok("{'x': a.pop()} if t else {'x': b}") is False


# --- the gate fires strictly at LEARN time, not only downstream --------------

def test_container_gate_excludes_at_learn_time_directly():
    # Not merely filtered downstream by mind_candidate_exprs — the exemplar
    # must never even enter the learned corpus.
    ex = learn_return_exemplars(["def f(a):\n    return {'x': a.pop()}\n"])
    assert ex == []
    assert mind_candidate_exprs(
        ["def f(a):\n    return {'x': a.pop()}\n"], ("q",)) == []


# --- inlined-temps composition still routes through its OWN fold-path gate ---

def test_inlined_temp_building_a_container_uses_the_fold_paths_own_gate():
    # `x = {"a": p}; return x` folds via the inlined-temps path (its own
    # _method_call_count(folded) > 1 check), NOT the new container gate merged
    # in — a single pure element stays learnable either way.
    ex = learn_return_exemplars(["def f(a):\n    x = {'a': a}\n    return x\n"])
    assert [(e.name, e.expr) for e in ex] == [("f", "{'a': a}")]


# --- ADAPT: the shared canonical_shape/adapt path works UNCHANGED ------------

def test_adapt_remaps_dict_literal_positionally():
    assert adapt_expr_to_params(("a", "b"), "{'x': a, 'y': b}", ("p", "q")) == (
        "{'x': p, 'y': q}")


def test_adapt_remaps_list_literal_positionally():
    assert adapt_expr_to_params(("a", "b"), "[a, b]", ("p", "q")) == "[p, q]"


def test_adapt_remaps_tuple_literal_positionally():
    assert adapt_expr_to_params(("a", "b"), "(a, b)", ("p", "q")) == "(p, q)"


def test_canonical_shape_positional_for_container_literal():
    assert canonical_shape(("a", "b"), "{'x': a, 'y': b}") == "2:{'x': p0, 'y': p1}"


def test_candidates_include_a_container_shape():
    corpus = ["def f(a, b):\n    return {'x': a, 'y': b}\n"]
    candidates = mind_candidate_exprs(corpus, ("p", "q"))
    assert ("native-mind:f", "{'x': p, 'y': q}") in candidates


# --- REGRESSION: the four prior shapes stay byte-identical -------------------

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


def test_regression_comprehension_shape_unchanged():
    ex = learn_return_exemplars(["def dbl(a):\n    return [x * 2 for x in a]\n"])
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("dbl", ("a",), "[x * 2 for x in a]")]


def test_regression_name_aware_adapt_unchanged():
    assert adapt_expr_to_params(("a", "b"), "a - b", ("b", "a")) == "a - b"


# --- REGRESSION: byte-identical re-run of the OTHER fixture files' corpora ---
# Pins that the new gate never drops/reorders an exemplar the prior shapes
# already learned — each corpus below is copied verbatim from the named file's
# own tests, and the expected output is exactly what that file already pins.

def test_regression_corpus_from_eyml_file_byte_identical():
    corpus = ["def add(a, b):\n    return a + b\n",
              "def shout(s):\n    return s.upper()\n"]
    got = {(e.name, e.params, e.expr) for e in learn_return_exemplars(corpus)}
    assert got == {("add", ("a", "b"), "a + b"), ("shout", ("s",), "s.upper()")}


def test_regression_corpus_from_elif_eyml_file_byte_identical():
    corpus = [
        "def rank(a, b, c):\n    if a > b:\n        return a\n    elif b > c:\n"
        "        return b\n    elif a > c:\n        return c\n    else:\n"
        "        return a\n",
    ]
    ex = learn_return_exemplars(corpus)
    assert [(e.name, e.expr) for e in ex] == [
        ("rank", "a if a > b else b if b > c else c if a > c else a")]


def test_regression_corpus_from_inline_temps_eyml_file_byte_identical():
    corpus = ["def f(a):\n    x = a + 1\n    y = x * 2\n    z = y - 1\n    return z\n"]
    ex = learn_return_exemplars(corpus)
    assert [(e.name, e.expr) for e in ex] == [("f", "(a + 1) * 2 - 1")]


def test_regression_corpus_from_comprehensions_eyml_file_byte_identical():
    corpus = ["def combine(a, b):\n    return [a + x for x in b]\n"]
    ex = learn_return_exemplars(corpus)
    assert [(e.name, e.params, e.expr) for e in ex] == [
        ("combine", ("a", "b"), "[a + x for x in b]")]


def test_regression_corpus_from_name_aware_eyml_file_byte_identical():
    corpus = ["def sub(a, b):\n    return a - b\n"]
    stub_src = ('def diff(b, a):\n    """Diff.\n\n    >>> diff(3, 10)\n    7\n'
                '    >>> diff(1, 5)\n    4\n    """\n    raise NotImplementedError\n')
    stub = find_stub_functions(stub_src)[0]
    assert stub.params == ("b", "a")
    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = (label, expr)
            break
    assert landed == ("native-mind:sub", "a - b")


def test_regression_corpus_from_patterns_eyml_file_byte_identical():
    corpus = [
        "def a1(a, b):\n    return a - b\n",
        "def a2(m, n):\n    return m - n\n",
        "def a3(p, q):\n    return p - q\n",
        "def a4(x, y):\n    return x + y\n",
    ]
    ranked = [expr for _label, expr in mind_candidate_exprs(corpus, ("u", "v"))]
    assert ranked == ["u - v", "u + v"]


# --- determinism ---------------------------------------------------------------

def test_determinism_pin():
    corpus = [
        "def f(a, b):\n    return {'x': a, 'y': b}\n",
        "def g(a, b):\n    return [a, b]\n",
        "def h(a, b):\n    return (a, b)\n",
        "def guarded(t, a, b):\n    if t:\n        return {'x': a}\n    return {'x': b}\n",
    ]
    first = learn_return_exemplars(corpus)
    for _ in range(5):
        assert learn_return_exemplars(corpus) == first
    first_c = mind_candidate_exprs(corpus, ("p", "q"))
    for _ in range(5):
        assert mind_candidate_exprs(corpus, ("p", "q")) == first_c


# --- end-to-end: propose via mind_candidate_exprs, gate disposes -------------

def test_container_candidate_lands_through_the_doctest_gate():
    corpus = ["def make(a, b):\n    return {'x': a, 'y': b}\n"]
    stub_src = (
        'def build(p, q):\n    """Build.\n\n'
        "    >>> build(1, 2)\n    {'x': 1, 'y': 2}\n"
        "    >>> build(3, 4)\n    {'x': 3, 'y': 4}\n"
        '    """\n    raise NotImplementedError\n'
    )
    stub = find_stub_functions(stub_src)[0]
    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = (label, expr)
            break
    assert landed == ("native-mind:make", "{'x': p, 'y': q}")


def test_wrong_container_candidate_is_refused_by_the_gate():
    # A learned body swaps 'x'/'y' relative to the stub's contract -> refused.
    corpus = ["def make(a, b):\n    return {'y': a, 'x': b}\n"]
    stub_src = (
        'def build(p, q):\n    """Build.\n\n'
        "    >>> build(1, 2)\n    {'x': 1, 'y': 2}\n"
        '    """\n    raise NotImplementedError\n'
    )
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


def test_container_lands_end_to_end_through_synthesize_expr_from_witnesses(
        tmp_path, monkeypatch):
    """A stub whose only correct body is a learned dict-literal exemplar: no
    fixed template builds a dict literal, so this only lands with the
    native-mind lane on. Proves the real doctest verification gate lands a
    new-shape exemplar end to end."""
    from app.execution.stub_synthesis import synthesize_expr_from_witnesses

    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py",
           "def make(a, b):\n    return {'x': a, 'y': b}\n")
    _write(tmp_path, "pkg/build.py", "def build(p, q):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_build.py", """
        from pkg.build import build

        def test_pair():
            assert build(1, 2) == {'x': 1, 'y': 2}

        def test_other():
            assert build(5, 9) == {'x': 5, 'y': 9}
        """)
    src = (tmp_path / "pkg" / "build.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]

    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_build.py"], stub) is None

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_build.py"], stub) == "{'x': p, 'y': q}"


def test_wrong_container_candidate_refused_end_to_end_through_the_wire_in(
        tmp_path, monkeypatch):
    """A wrong-shape (mismatched literal values) candidate must be REFUSED by
    the real gate, with no diff applied — proves the auto-rollback / never-
    fake-green path is exercised for the new shape, not just proposed."""
    from app.execution.stub_synthesis import synthesize_expr_from_witnesses

    _write(tmp_path, "pkg/__init__.py", "")
    # Exemplar swaps the keys relative to the stub's own contract.
    _write(tmp_path, "pkg/lib.py",
           "def make(a, b):\n    return {'y': a, 'x': b}\n")
    _write(tmp_path, "pkg/build.py", "def build(p, q):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_build.py", """
        from pkg.build import build

        def test_pair():
            assert build(1, 2) == {'x': 1, 'y': 2}
        """)
    src = (tmp_path / "pkg" / "build.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_build.py"], stub) is None
