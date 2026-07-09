"""Native intelligence (v0) — the THIRD finishable body shape: ELIF CHAINS.

Beyond a plain ``return <expr>`` and a two-branch guarded return, the native
intelligence now learns an arbitrary-length elif chain (every branch a sole
``return <expr>``, terminated by a final ``else`` or a trailing fallthrough) as
the equivalent RIGHT-NESTED ternary — ``A if T1 else (B if T2 else C)`` — a
single expression it can transplant exactly like the other two shapes (same
positional remap, same never-fake-green gate). These tests pin the new shape AND
its boundaries (what stays UN-learnable), and prove the two prior shapes stay
byte-identical.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.engine.native_synth import learn_return_exemplars, mind_candidate_exprs
from app.execution.stub_synthesis import (
    _native_mind_sources,
    find_stub_functions,
    synthesize_expr_from_witnesses,
    verify_body_via_doctest,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


# --- learning the elif-chain shape --------------------------------------------

def test_length_2_chain_with_final_else():
    # if T1: return A / elif T2: return B / else: return C
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return b\n    else:\n        return -1\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [
        ("t", "a if a > b else b if a == b else -1")]


def test_length_2_chain_with_trailing_fallthrough():
    # if T1: return A / elif T2: return B / (trailing) return C
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return b\n    return a\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [
        ("t", "a if a > b else b if a == b else a")]


def _elif_chain_src(n: int) -> str:
    """A dispatch-style ``def t(a): if a==0: return 0 / elif ... / else: return
    -1`` with ``n`` elif links — every branch self-contained (only ``a`` + int
    literals)."""
    lines = ["def t(a):", "    if a == 0:", "        return 0"]
    for i in range(1, n):
        lines += [f"    elif a == {i}:", f"        return {i}"]
    lines += ["    else:", "        return -1"]
    return "\n".join(lines) + "\n"


def test_medium_elif_chain_is_learned_iteratively():
    # A 40-link chain collapses to the right-nested ternary — proves the builder
    # scales past the hand-written length-2/3 cases without recursion.
    ex = learn_return_exemplars([_elif_chain_src(40)])
    assert len(ex) == 1
    assert ex[0].expr.startswith("0 if a == 0 else 1 if a == 1 else ")
    assert ex[0].expr.endswith("else -1")


def test_pathological_elif_chain_never_raises():
    # A dispatch-table-sized chain mined from a real source file must NEVER crash
    # the whole native-mind scan (regression: _elif_link_value once recursed
    # unbounded and the RecursionError escaped the pipeline, violating
    # summarize_native_mind's "never raises" contract). It fails CLOSED — returns
    # a list (learned, or empty if ast.unparse itself bottoms out) — never raises.
    result = learn_return_exemplars([_elif_chain_src(1500)])
    assert isinstance(result, list)


def test_length_3_chain_with_final_else():
    # if T1 / elif T2 / elif T3 / else -- one more link than the length-2 case.
    ex = learn_return_exemplars([
        "def rank(a, b, c):\n    if a > b:\n        return a\n    elif b > c:\n"
        "        return b\n    elif a > c:\n        return c\n    else:\n"
        "        return a\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [
        ("rank", "a if a > b else b if b > c else c if a > c else a")]


def test_length_3_chain_with_trailing_fallthrough():
    ex = learn_return_exemplars([
        "def rank(a, b, c):\n    if a > b:\n        return a\n    elif b > c:\n"
        "        return b\n    elif a > c:\n        return c\n    return a\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [
        ("rank", "a if a > b else b if b > c else c if a > c else a")]


def test_docstring_is_skipped_before_elif_chain():
    ex = learn_return_exemplars([
        'def t(a, b):\n    """doc"""\n    if a > b:\n        return a\n    elif a == b:\n'
        '        return b\n    else:\n        return -1\n',
    ])
    assert [(e.name, e.expr) for e in ex] == [
        ("t", "a if a > b else b if a == b else -1")]


# --- boundaries: what stays UN-learnable --------------------------------------

def test_chain_with_no_final_else_or_fallthrough_is_not_learned():
    # elif with nothing after it -> the last branch has no value -> incomplete.
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return b\n",
    ])
    assert ex == []


def test_chain_with_dead_trailing_code_after_a_final_else_is_not_learned():
    # A complete if/elif/else already covers every case; a trailing return after
    # it is unreachable/richer code, not the clean fallthrough shape.
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return b\n    else:\n        return -1\n    return a\n",
    ])
    assert ex == []


def test_branch_that_is_not_a_sole_return_is_not_learned():
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        x = 1\n        return x\n    return a\n",
    ])
    assert ex == []


def test_bare_return_in_a_chain_branch_is_not_learned():
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return\n    return a\n",
    ])
    assert ex == []


def test_free_name_in_a_chain_branch_is_not_learned():
    # Self-containment: a branch reading a global disqualifies the whole chain.
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return GLOBAL\n    return a\n",
    ])
    assert ex == []


def test_binding_node_in_a_chain_branch_is_not_learned():
    # A walrus in a branch introduces a bound name the Name-load scan can't vet.
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return (z := b)\n    return a\n",
    ])
    assert ex == []


def test_statement_around_the_chain_is_not_learned():
    ex = learn_return_exemplars([
        "def t(a, b):\n    if a > b:\n        return a\n    elif a == b:\n"
        "        return b\n    c = a\n    return c\n",
    ])
    assert ex == []


def test_plain_if_else_is_still_the_two_branch_shape_not_elif_chain():
    # No `elif` link at all -> declined by the elif-chain helper; still learned
    # (byte-identically) via the two-branch guarded-return shape.
    ex = learn_return_exemplars([
        "def pick(a, b):\n    if a > b:\n        return a\n    else:\n        return b\n",
    ])
    assert [(e.name, e.expr) for e in ex] == [("pick", "a if a > b else b")]


# --- REGRESSION: prior two shapes stay byte-identical -------------------------

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


# --- determinism ---------------------------------------------------------------

def test_learning_elif_chains_is_deterministic():
    corpus = [
        "def rank(a, b, c):\n    if a > b:\n        return a\n    elif b > c:\n"
        "        return b\n    else:\n        return c\n",
        "def add(a, b):\n    return a + b\n",
    ]
    first = learn_return_exemplars(corpus)
    for _ in range(5):
        assert learn_return_exemplars(corpus) == first


# --- end-to-end: proposed, then the EXISTING gate disposes --------------------

def test_elif_chain_exemplar_adapts_and_lands_through_the_gate():
    corpus = [
        "def sign_cmp(a, b):\n    if a > b:\n        return 1\n    elif a < b:\n"
        "        return -1\n    else:\n        return 0\n",
    ]
    stub_src = (
        'def cmp3(x, y):\n    """Compare.\n\n    >>> cmp3(5, 2)\n    1\n'
        '    >>> cmp3(2, 5)\n    -1\n    >>> cmp3(3, 3)\n    0\n    """\n'
        "    raise NotImplementedError\n"
    )
    stub = find_stub_functions(stub_src)[0]
    landed = None
    for label, expr in mind_candidate_exprs(corpus, stub.params):
        if verify_body_via_doctest(stub_src, stub, expr):
            landed = (label, expr)
            break
    assert landed == (
        "native-mind:sign_cmp", "1 if x > y else -1 if x < y else 0")


def test_elif_chain_wrong_shape_is_refused_by_the_gate():
    corpus = [
        "def sign_cmp(a, b):\n    if a > b:\n        return 1\n    elif a < b:\n"
        "        return -1\n    else:\n        return 0\n",
    ]
    # Contract wants the MAX, not a three-way sign -> the learned body refused.
    stub_src = (
        'def bigger(x, y):\n    """Bigger.\n\n    >>> bigger(3, 5)\n    5\n'
        '    >>> bigger(9, 2)\n    9\n    """\n    raise NotImplementedError\n'
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


def test_elif_chain_transplants_through_stub_synthesis_wire_in(tmp_path, monkeypatch):
    """A stub no fixed template covers (a three-way sign) is finished ONLY via the
    native-mind lane, transplanting the project's own elif-chain exemplar."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py",
           "def sign_cmp(a, b):\n    if a > b:\n        return 1\n    elif a < b:\n"
           "        return -1\n    else:\n        return 0\n")
    _write(tmp_path, "pkg/cmp.py", "def cmp3(x, y):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_cmp.py", """
        from pkg.cmp import cmp3

        def test_gt():
            assert cmp3(5, 2) == 1

        def test_lt():
            assert cmp3(2, 5) == -1

        def test_eq():
            assert cmp3(3, 3) == 0
        """)
    src = (tmp_path / "pkg" / "cmp.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]

    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_cmp.py"], stub) is None  # no template covers a 3-way sign

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_cmp.py"], stub) == "1 if x > y else -1 if x < y else 0"
