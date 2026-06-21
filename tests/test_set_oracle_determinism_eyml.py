"""Determinism guard for the value-oracle source literal (P1 fix, eyml).

The shared value-oracle helper used to emit ``repr(value)`` of a captured return
value straight into LANDED test code. For a ``set`` of STRINGS the ``repr``
element order is ``PYTHONHASHSEED``-dependent (str hashing is randomized), so two
CI runs landed DIFFERENT git diffs for the same project — and the double-gate did
NOT catch it because set equality is order-independent. This module pins the fix:
:func:`_canonical_repr` renders a deterministic, order-stable source literal, and
:func:`_captured_oracle` emits THAT (re-validated) instead of the raw ``repr``.
"""

import ast

from app.execution.test_shield import _canonical_repr, _captured_oracle


def test_canonical_repr_set_of_strings_is_sorted_and_byte_stable():
    # Build the SAME logical set in two different insertion orders.
    one = {"alpha", "beta", "gamma", "eta"}
    two = set(reversed(["alpha", "beta", "gamma", "eta"]))
    out_one = _canonical_repr(one)
    out_two = _canonical_repr(two)
    # Order of construction must not change a single byte of output.
    assert out_one == out_two
    # And the output equals the explicitly-sorted form of the elements.
    expected = "{" + ", ".join(sorted(repr(s) for s in one)) + "}"
    assert out_one == expected


def test_canonical_repr_empty_set_renders_set_call_and_round_trips():
    out = _canonical_repr(set())
    assert out == "set()"
    assert ast.literal_eval(out) == set()


def test_captured_oracle_set_of_strings_byte_identical_regardless_of_order():
    s_a = {"b", "a", "c"}
    s_b = set(reversed(["b", "a", "c"]))
    oracle_a = _captured_oracle(repr(s_a), s_a)
    oracle_b = _captured_oracle(repr(s_b), s_b)
    assert oracle_a is not None
    # The emitted literal round-trips to the captured value.
    assert ast.literal_eval(oracle_a) == s_a
    # Byte-identical no matter the insertion order of the captured set.
    assert oracle_a == oracle_b
    # It equals the sorted-rendered literal.
    expected = "{" + ", ".join(sorted(repr(x) for x in s_a)) + "}"
    assert oracle_a == expected


def test_nested_list_containing_a_set_is_canonicalized():
    one = [{"b", "a"}]
    two = [set(reversed(["b", "a"]))]
    out_one = _canonical_repr(one)
    out_two = _canonical_repr(two)
    assert out_one == out_two
    assert out_one == "[{'a', 'b'}]"
    assert ast.literal_eval(out_one) == [{"a", "b"}]


def test_frozenset_still_declines_to_an_oracle():
    fs = frozenset({"x", "y"})
    # frozenset repr (``frozenset({...})``) is rejected by ast.literal_eval, so
    # the existing round-trip guard turns it into None — unchanged behaviour.
    assert _captured_oracle(repr(fs), fs) is None


def test_list_and_tuple_order_is_preserved_dict_keys_are_sorted():
    # Lists keep insertion order (NOT sorted) — order is semantically meaningful.
    assert _canonical_repr(["b", "a"]) == "['b', 'a']"
    # Tuples keep insertion order.
    assert _canonical_repr(("b", "a")) == "('b', 'a')"
    # Dicts render with keys SORTED by canonical key repr: dict eq ignores order,
    # so this is byte-stable across hash seeds with NO change to assertion validity
    # (a dict whose key order is set-iteration-derived would otherwise flake).
    assert _canonical_repr({"b": 1, "a": 2}) == "{'a': 2, 'b': 1}"
    assert ast.literal_eval("{'a': 2, 'b': 1}") == {"b": 1, "a": 2}


def test_single_element_tuple_keeps_trailing_comma():
    out = _canonical_repr(("only",))
    assert out == "('only',)"
    assert ast.literal_eval(out) == ("only",)


def test_dict_of_ints_round_trips_and_is_stable():
    d = {1: 10, 2: 20, 3: 30}
    out = _canonical_repr(d)
    assert _canonical_repr(d) == out  # stable
    assert ast.literal_eval(out) == d


def test_set_of_ints_round_trips_and_is_stable():
    s = {3, 1, 2}
    out = _canonical_repr(s)
    assert _canonical_repr(set(reversed([3, 1, 2]))) == out  # order-independent
    assert ast.literal_eval(out) == s


def test_tuple_round_trips_and_is_stable():
    t = (1, "x", 2.5, None, True)
    out = _canonical_repr(t)
    assert _canonical_repr(t) == out
    assert ast.literal_eval(out) == t


def test_canonical_repr_does_not_depend_on_set_iteration_order():
    # Strong proof of the hash-seed independence: construct a set of strings,
    # then re-construct it from the reversed-sorted elements; outputs are equal.
    base = {"delta", "alpha", "charlie", "bravo"}
    rebuilt = set(reversed(sorted(base)))
    assert _canonical_repr(base) == _canonical_repr(rebuilt)


def test_scalars_delegate_to_repr():
    for value in (None, True, False, 0, -7, 3.14, "hi", ""):
        assert _canonical_repr(value) == repr(value)
        assert ast.literal_eval(_canonical_repr(value)) == value


def test_set_with_mixed_unorderable_elements_is_still_deterministic():
    # ints and strings are not mutually orderable; sorting by canonical repr (a
    # total STRING order) keeps rendering deterministic and round-tripping.
    s = {1, "a", 2, "b"}
    out_one = _canonical_repr(s)
    out_two = _canonical_repr(set(reversed([1, "a", 2, "b"])))
    assert out_one == out_two
    assert ast.literal_eval(out_one) == s
