"""Native intelligence (v0) — NAME-AWARE param alignment + cross-arity subset
adaptation. Raises the ADAPT hit-rate on TWO fronts, both unambiguous (keyed
only by param NAME, never a guess):

* (2a) SAME arity: when the stub reuses the exemplar's own param names in a
  DIFFERENT order (``a - b`` learned from ``(a, b)``, transplanted onto a stub
  ``(b, a)``), align by NAME instead of position — the old positional rule
  mis-adapted this to ``b - a`` (wrong for a non-commutative idiom); the
  name-aware rule keeps ``a - b`` (right). Every other case — same names same
  order, or no shared names at all — stays BYTE-IDENTICAL to the prior
  positional behaviour.
* (2b) Cross arity: a SMALLER exemplar whose param names are a DISTINCT SUBSET
  of a WIDER stub's names now adapts (a 2-arg idiom finishes a 3-arg stub that
  reuses those two names), instead of being skipped outright by the old
  same-arity-only guard. No shared names -> refused (``None``), never guessed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.engine.native_synth import (
    adapt_expr_to_params,
    canonical_shape,
    mind_candidate_exprs,
)
from app.execution.stub_synthesis import (
    _native_mind_sources,
    _ordered_candidates,
    find_stub_functions,
    verify_body_via_doctest,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


# --- (2a) name-aware alignment, same arity -----------------------------------

def test_name_aware_swap_keeps_correct_non_commutative_order():
    # Old positional rule: a->b, b->a -> "b - a" (WRONG). Name-aware: a->a,
    # b->b (the stub's OWN same-named params) -> "a - b" (RIGHT).
    assert adapt_expr_to_params(("a", "b"), "a - b", ("b", "a")) == "a - b"


def test_name_aware_same_order_is_still_a_no_op():
    assert adapt_expr_to_params(("a", "b"), "a - b", ("a", "b")) == "a - b"


def test_name_aware_falls_back_to_positional_when_no_names_shared():
    # No shared names -> BYTE-IDENTICAL to the original positional rule.
    assert adapt_expr_to_params(("a", "b"), "a - b", ("x", "y")) == "x - y"


def test_name_aware_partial_overlap_falls_back_to_positional():
    # Only ONE of the two exemplar names is present in the stub -> "every
    # exemplar name present" fails -> positional fallback, not a partial remap.
    assert adapt_expr_to_params(("a", "b"), "a - b", ("a", "z")) == "a - z"


# --- (2b) unambiguous cross-arity subset --------------------------------------

def test_cross_arity_two_arg_idiom_onto_three_arg_stub():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("a", "b", "c")) == "a + b"


def test_cross_arity_one_arg_idiom_onto_two_arg_stub():
    assert adapt_expr_to_params(("a",), "a * 2", ("a", "b")) == "a * 2"


def test_cross_arity_no_shared_names_is_refused():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("x", "y", "z")) is None


def test_exemplar_arity_greater_than_stub_is_refused():
    assert adapt_expr_to_params(("a", "b", "c"), "a + b + c", ("x", "y")) is None


def test_cross_arity_subset_must_be_distinct_names_not_a_coincidence():
    # A single shared name out of two is not a full subset -> refused, never a
    # partial/guessed mapping.
    assert adapt_expr_to_params(("a", "b"), "a + b", ("a", "y", "z")) is None


# --- byte-identical regression pins (the positional path is untouched) ------

def test_regression_positional_path_is_byte_identical():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("x", "y")) == "x + y"


def test_regression_identity_path_is_byte_identical():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("a", "b")) == "a + b"


def test_regression_arity_mismatch_wider_exemplar_stays_none():
    assert adapt_expr_to_params(("a", "b"), "a + b", ("x",)) is None


def test_regression_attribute_access_untouched():
    assert adapt_expr_to_params(("s",), "s.upper()", ("t",)) == "t.upper()"


# --- end-to-end via mind_candidate_exprs -------------------------------------

def test_two_arg_idiom_surfaces_as_a_candidate_for_a_three_arg_stub():
    corpus = ["def add(a, b):\n    return a + b\n"]
    candidates = mind_candidate_exprs(corpus, ("a", "b", "c"))
    assert ("native-mind:add", "a + b") in candidates


def test_no_shared_names_cross_arity_yields_no_candidate():
    corpus = ["def add(a, b):\n    return a + b\n"]
    assert mind_candidate_exprs(corpus, ("x", "y", "z")) == []


def test_wider_exemplar_than_stub_yields_no_candidate():
    corpus = ["def add3(a, b, c):\n    return a + b + c\n"]
    assert mind_candidate_exprs(corpus, ("x", "y")) == []


def test_name_aware_swap_lands_through_the_verifier():
    # `sub` learned as (a, b) -> a - b; the stub's OWN params are (b, a) — a
    # non-commutative idiom whose ONLY correct adaptation is the name-aware one.
    # The old positional rule would have produced "b - a", which FAILS these
    # very doctests (3 - 10 == -7, not 7) and lands nothing; the name-aware
    # rule produces "a - b" and lands.
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


def test_determinism_same_sources_and_stub_same_ordered_candidates():
    corpus = [
        "def add(a, b):\n    return a + b\n",
        "def sub(a, b):\n    return a - b\n",
        "def add3(a, b, c):\n    return a + b + c\n",
    ]
    first = mind_candidate_exprs(corpus, ("a", "b", "c"))
    for _ in range(5):
        assert mind_candidate_exprs(corpus, ("a", "b", "c")) == first


def test_determinism_name_aware_swap_case():
    corpus = ["def sub(a, b):\n    return a - b\n"]
    first = mind_candidate_exprs(corpus, ("b", "a"))
    for _ in range(5):
        assert mind_candidate_exprs(corpus, ("b", "a")) == first


# --- end-to-end via the real wire-in path (opt-in APEX_NATIVE_MIND lane) ------

@pytest.fixture(autouse=True)
def _clean_native_cache():
    _native_mind_sources.cache_clear()
    yield
    _native_mind_sources.cache_clear()


def test_cross_arity_idiom_is_wired_into_the_real_candidate_path(
        tmp_path, monkeypatch):
    """A project-mined 2-arg idiom (``clamp``'s guarded shape, not one of the
    fixed 3-arg arithmetic templates) surfaces as a native-mind candidate for a
    3-arg stub whose signature reuses two of its param names — through the SAME
    ``_ordered_candidates`` path ``synthesize_expr_from_witnesses`` uses. Absent
    with the lane off (byte-identical template core), present with it on."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py",
           "def pick(a, b):\n    if a > b:\n        return a\n    else:\n        return b\n")
    _write(tmp_path, "pkg/widen.py",
           "def widen(a, b, c):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_widen.py", """
        from pkg.widen import widen

        def test_pair():
            assert widen(3, 5, 0) == 5
        """)
    src = (tmp_path / "pkg" / "widen.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]
    assert stub.params == ("a", "b", "c")

    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()
    off = _ordered_candidates(tmp_path, ["tests/test_widen.py"], stub)
    assert all(not label.startswith("native-mind:") for label, _ in off)

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    on = _ordered_candidates(tmp_path, ["tests/test_widen.py"], stub)
    assert ("native-mind:pick", "a if a > b else b") in on


# --- canonicalisation stays POSITIONAL (must NOT inherit the name-aware rule) --
# Regression for a collision the name-aware ADAPT rule introduced into
# canonical_shape (the persistent experience key): when a real param is spelled
# like the placeholder alphabet (p0/p1 — plausible in point/geometry code), the
# identity short-circuit spliced the body verbatim BY NAME, dropping the
# positional rename, so two OPPOSITE idioms could key to the same string and
# silently corrupt native_proof_memory's decay store. canonical_shape must
# canonicalise strictly BY POSITION.

def test_canonical_shape_is_positional_even_for_placeholder_named_params():
    # (p1, p0) returning `p0 - p1` is "second - first" -> keyed p1 - p0, NOT the
    # verbatim `p0 - p1` the name-aware rule would have spliced.
    assert canonical_shape(("p1", "p0"), "p0 - p1") == "2:p1 - p0"


def test_canonical_shape_does_not_collide_opposite_idioms():
    first_minus_second = canonical_shape(("x", "y"), "x - y")       # p0 - p1
    second_minus_first = canonical_shape(("p1", "p0"), "p0 - p1")   # p1 - p0
    assert first_minus_second == "2:p0 - p1"
    assert second_minus_first == "2:p1 - p0"
    assert first_minus_second != second_minus_first  # opposite idioms, distinct keys


def test_canonical_shape_unchanged_for_ordinary_names():
    # The common case is byte-identical to before capability #2.
    assert canonical_shape(("a", "b"), "a + b") == "2:p0 + p1"
    assert canonical_shape(("m", "n"), "m - n") == "2:p0 - p1"
    assert canonical_shape(("a", "b", "c"), "a + b") == "3:p0 + p1"
