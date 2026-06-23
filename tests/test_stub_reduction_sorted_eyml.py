"""1-arg SOUND, GENERALIZING reduction families for implement-stub synthesis.

This suite covers two NEW value-free / witness-derived 1-arg reduction shapes:

* ``return len(set(a))`` — the DISTINCT-count: the number of UNIQUE elements of a
  hashable sequence. ``n_unique([1, 2, 2]) == 2, n_unique([5, 5, 5, 6]) == 2,
  n_unique([7, 8, 9]) == 3`` lands ``return len(set(xs))`` — a value no other 1-arg
  shape spells (``len`` counts WITH duplicates). The cardinality of a set is a
  deterministic ``int`` (PYTHONHASHSEED-safe — a count, never a materialized set's
  iteration order), so the determinism invariant holds even though a bare ``set(a)``
  return is forbidden.
* ``return sorted(a)[k]`` — the k-th SMALLEST element (``k == 0`` min, ``k == -1``
  max, ``k == 1`` second-smallest). ``second_smallest([3, 1, 2]) == 2,
  ([5, 9, 1]) == 5, ([8, 4, 6, 2]) == 4`` lands ``return sorted(xs)[1]`` — an INTERIOR
  order statistic neither the constant index ``a[k]`` (the element AT a position) nor
  ``min`` / ``max`` (the endpoints) can spell. ``k`` is mined over a BOUNDED index set
  (indices valid for the SHORTEST witnessed sequence, plus the anchors
  ``0`` / ``1`` / ``-1`` / ``-2``) and VERIFIED with ``sorted(seq)[k] == out`` for
  EVERY witness.

Both reuse the existing sound machinery: the type-exact accept-gate, the off-witness
sequence canary (the sole fake-green arbiter), the >=2-distinct-witness overfit floor,
and the ambiguity arbiter. GUARDS pinned here: ``len(set(a))`` is offered only for a
hashable sequence whose distinct count VARIES and genuinely differs from a plain
``len`` (NO-SHADOW); ``sorted(a)[k]`` requires every witnessed sequence ORDERABLE and
``k`` in range for EVERY witness (else the candidate is simply invalid, not an
exception); the expected values must VARY (an all-equal contract collapses to a
constant — refused); type-exact; ambiguity-refuse on >=2 survivors; and DEFER /
no-shadow when a simpler atom (``min`` / ``max`` / ``len`` / ``a[k]``) already fits, so
the families fire ONLY for a contract no simpler body solves.
"""

from __future__ import annotations

from pathlib import Path


# --- helpers -----------------------------------------------------------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _plan_body(tmp_path: Path, module: str, src: str, test_src: str) -> str | None:
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / module).write_text(src, encoding="utf-8")
    (tmp_path / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    rel = f"app/{module}"
    return plan_implement_stub(str(tmp_path), rel).new_contents.get(rel)


# --- LANDED: distinct-count ``len(set(a))`` ----------------------------------

def test_distinct_count_lands_end_to_end(tmp_path: Path):
    # n_unique([1, 2, 2]) == 2, ([5, 5, 5, 6]) == 2, ([7, 8, 9]) == 3 -> len(set(xs)).
    # The number of DISTINCT elements: [1,2,2] has 2, [5,5,5,6] has 2, [7,8,9] has 3.
    # A value plain `len` cannot give (it counts duplicates: 3/4/3). The body lands
    # end-to-end through the real pytest-gated plan.
    body = _plan_body(
        tmp_path, "dc.py",
        "def n_unique(xs):\n    raise NotImplementedError\n",
        "from app.dc import n_unique\n"
        "def test():\n"
        "    assert n_unique([1, 2, 2]) == 2\n"
        "    assert n_unique([5, 5, 5, 6]) == 2\n"
        "    assert n_unique([7, 8, 9]) == 3\n")
    assert body is not None and "return len(set(xs))" in body


def test_distinct_count_on_str_lands(tmp_path: Path):
    # n_distinct('aab') == 2, ('cccd') == 2, ('xyz') == 3 -> len(set(s)). A str is a
    # sequence of hashable chars, so the distinct-count generalizes to it.
    body = _plan_body(
        tmp_path, "dcs.py",
        "def n_distinct(s):\n    raise NotImplementedError\n",
        "from app.dcs import n_distinct\n"
        "def test():\n"
        "    assert n_distinct('aab') == 2\n"
        "    assert n_distinct('cccd') == 2\n"
        "    assert n_distinct('xyz') == 3\n")
    assert body is not None and "return len(set(s))" in body


# --- LANDED: order statistic ``sorted(a)[k]`` --------------------------------

def test_second_smallest_lands_end_to_end(tmp_path: Path):
    # second([3, 1, 2]) == 2, ([5, 9, 1]) == 5, ([8, 4, 6, 2]) == 4 -> sorted(xs)[1].
    # The second-smallest is an INTERIOR order statistic no atom spells: xs[1] gives
    # 1/9/4 (wrong), min gives 1/1/2 (wrong), max gives 3/9/8 (wrong). The length-4
    # witness [8,4,6,2] breaks the k=1 vs k=-2 tie (sorted[-2] would be 6 there, != 4),
    # so k=1 is the UNIQUE survivor and lands.
    body = _plan_body(
        tmp_path, "ss.py",
        "def second(xs):\n    raise NotImplementedError\n",
        "from app.ss import second\n"
        "def test():\n"
        "    assert second([3, 1, 2]) == 2\n"
        "    assert second([5, 9, 1]) == 5\n"
        "    assert second([8, 4, 6, 2]) == 4\n")
    assert body is not None and "return sorted(xs)[1]" in body


def test_sorted_index_family_mines_min_max_second():
    # The family helper (in isolation, no simpler atoms supplied) mines the unique k for
    # min (k=0), max (k=-1) and second-smallest (k=1). These are exactly the ACCEPTS the
    # capability promises; end-to-end the min/max cases DEFER to the simpler min(a)/max(a)
    # atoms (see the no-shadow tests), but the order-statistic family OWNS the mining.
    from app.execution.stub_synthesis import _sorted_index_templates

    # min: sorted(xs)[0] over varying-output witnesses (outputs 1/5/4 vary).
    assert _sorted_index_templates(
        "xs", [("[3, 1, 2]", "1"), ("[5, 9, 7]", "5"), ("[8, 4, 6]", "4")],
    ) == [("sorted[0]", "sorted(xs)[0]")]
    # max: sorted(xs)[-1] (outputs 3/9/8 vary).
    assert _sorted_index_templates(
        "xs", [("[3, 1, 2]", "3"), ("[5, 9, 1]", "9"), ("[8, 4]", "8")],
    ) == [("sorted[-1]", "sorted(xs)[-1]")]
    # second-smallest: sorted(xs)[1], the length-4 witness resolving the k=1/k=-2 tie.
    assert _sorted_index_templates(
        "xs", [("[3, 1, 2]", "2"), ("[5, 9, 1]", "5"), ("[8, 4, 6, 2]", "4")],
    ) == [("sorted[1]", "sorted(xs)[1]")]


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "ss.py").write_text(
        "def second(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ss.py").write_text(
        "from app.ss import second\n"
        "def test():\n"
        "    assert second([3, 1, 2]) == 2\n"
        "    assert second([5, 9, 1]) == 5\n"
        "    assert second([8, 4, 6, 2]) == 4\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/ss.py").new_contents.get("app/ss.py")
    again = plan_implement_stub(str(tmp_path), "app/ss.py").new_contents.get("app/ss.py")
    assert first is not None and "return sorted(xs)[1]" in first
    assert first == again


# --- NO-SHADOW / DEFER: a simpler atom already fits --------------------------

def test_min_defers_to_simpler_min_atom(tmp_path: Path):
    # min([3, 1, 2]) == 1, ([5, 9, 7]) == 5, ([8, 4, 6]) == 4 is the MIN. sorted(xs)[0]
    # and min(xs) compute the SAME function, but min(xs) is the simpler, earlier atom, so
    # the sorted-index family DEFERS and min(xs) lands — a sorted body never shadows it.
    body = _plan_body(
        tmp_path, "mn.py",
        "def lo(xs):\n    raise NotImplementedError\n",
        "from app.mn import lo\n"
        "def test():\n"
        "    assert lo([3, 1, 2]) == 1\n"
        "    assert lo([5, 9, 7]) == 5\n"
        "    assert lo([8, 4, 6]) == 4\n")
    assert body is not None
    assert "sorted(" not in body  # deferred — min/etc. owns the contract

def test_sorted_index_defers_when_simpler_atom_fits():
    # Passing the simpler atoms that already fit (min/sorted) makes the family abstain
    # entirely (no-shadow), mirroring the compositional family's _simpler_template_fits.
    from app.execution.stub_synthesis import _sorted_index_templates

    ws = [("[3, 1, 2]", "1"), ("[5, 9, 7]", "5"), ("[8, 4, 6]", "4")]  # min contract
    # in isolation the family mines sorted(xs)[0]...
    assert _sorted_index_templates("xs", ws) == [("sorted[0]", "sorted(xs)[0]")]
    # ...but DEFERS once min(xs) is offered as a simpler atom.
    assert _sorted_index_templates("xs", ws, simpler=[("min", "min(xs)")]) == []


def test_distinct_count_defers_to_len_when_no_duplicate(tmp_path: Path):
    # size([1, 2, 3]) == 3, ([5, 6]) == 2 has NO duplicates, so len(set(xs)) == len(xs)
    # everywhere. The simpler, earlier len(xs) atom wins; the distinct-count is withheld
    # (NO-SHADOW), so the landed body uses len, never set.
    body = _plan_body(
        tmp_path, "ln.py",
        "def size(xs):\n    raise NotImplementedError\n",
        "from app.ln import size\n"
        "def test():\n"
        "    assert size([1, 2, 3]) == 3\n"
        "    assert size([5, 6]) == 2\n")
    assert body is not None
    assert "set(" not in body  # deferred — plain len owns a duplicate-free contract


# --- REFUSALS ----------------------------------------------------------------

def test_distinct_count_all_equal_outputs_refused():
    # n([1, 2, 2]) == 2, ([5, 5, 6]) == 2 has CONSTANT outputs (all 2): a shape that is
    # the same for every input collapses to a constant the constant-last fallback owns, so
    # the distinct-count family refuses rather than offer len(set(a)).
    from app.execution.stub_synthesis import (
        _distinct_count_applicable, _distinct_count_pairs,
    )

    ws = [("[1, 2, 2]", "2"), ("[5, 5, 6]", "2")]
    assert _distinct_count_pairs(ws) is None  # all-equal -> not minable
    assert _distinct_count_applicable(ws) is False


def test_sorted_index_all_equal_outputs_refused():
    # f([3, 1, 2]) == 1, ([5, 9, 1]) == 1 has CONSTANT outputs (all 1): an order statistic
    # that is constant collapses to a constant another family owns -> refuse.
    from app.execution.stub_synthesis import _sorted_index_pairs, _sorted_index_templates

    ws = [("[3, 1, 2]", "1"), ("[5, 9, 1]", "1")]
    assert _sorted_index_pairs(ws) is None  # all-equal -> not minable
    assert _sorted_index_templates("xs", ws) == []


def test_single_witness_floor_refused():
    # A LONE witness is below the >=2-distinct-witness floor: one example cannot tell
    # sorted(xs)[1] from a bare constant, so neither family mines a body.
    from app.execution.stub_synthesis import (
        _distinct_count_applicable, _sorted_index_templates,
    )

    assert _sorted_index_templates("xs", [("[3, 1, 2]", "2")]) == []
    assert _distinct_count_applicable([("[1, 2, 2]", "2")]) is False


def test_out_of_range_index_is_no_candidate():
    # An index out of range for SOME witness is simply NOT a candidate (never an
    # exception). With [9, 1, 5] -> 5 (sorted [1,5,9], [1]==5) and [7, 2] -> 7 (sorted
    # [2,7], [1]==7), the shortest sequence has length 2, so only k in {-2, -1, 0, 1} are
    # in range for EVERY witness; k=2 (valid only for the length-3 one) is excluded.
    from app.execution.stub_synthesis import _sorted_index_pairs, _sorted_index_set

    ws = [("[9, 1, 5]", "5"), ("[7, 2]", "7")]
    pairs = _sorted_index_pairs(ws)
    assert pairs is not None
    assert _sorted_index_set(pairs) == [-2, -1, 0, 1]  # k=2 dropped (oob for [7, 2])


def test_unorderable_mixed_witness_refused():
    # A mixed-type sequence ([1, 'a']) cannot be sorted (TypeError), so the candidate is
    # simply INVALID (not an exception): the miner returns None and the family refuses.
    from app.execution.stub_synthesis import _sorted_index_pairs, _sorted_index_templates

    ws = [("[1, 'a']", "1"), ("[2, 'b']", "2")]
    assert _sorted_index_pairs(ws) is None
    assert _sorted_index_templates("xs", ws) == []


def test_unhashable_witness_refuses_distinct_count():
    # A sequence of unhashable elements ([[1], [2]]) cannot form a set (TypeError), so the
    # distinct-count miner returns None and the family is withheld — no exception escapes.
    from app.execution.stub_synthesis import (
        _distinct_count_applicable, _distinct_count_pairs,
    )

    ws = [("[[1], [2]]", "2"), ("[[3]]", "1")]
    assert _distinct_count_pairs(ws) is None
    assert _distinct_count_applicable(ws) is False


def test_ambiguous_two_indices_fit_refused():
    # f([3, 1, 2]) == 2, ([5, 9, 1]) == 5, ([8, 4, 6]) == 6 is length-3-ONLY, where
    # sorted[1] AND sorted[-2] are the SAME middle position and both reproduce every
    # witness (2/5/6). The witnesses cannot tell which index is meant, so the family
    # REFUSES rather than guess (never-fake-green). The outputs VARY, so it is past the
    # constant floor.
    from app.execution.stub_synthesis import _sorted_index_pairs, _sorted_index_set, _sorted_index_holds, _sorted_index_templates

    ws = [("[3, 1, 2]", "2"), ("[5, 9, 1]", "5"), ("[8, 4, 6]", "6")]
    pairs = _sorted_index_pairs(ws)
    survivors = [k for k in _sorted_index_set(pairs) if _sorted_index_holds(k, pairs)]
    assert survivors == [-2, 1]  # two indices reproduce every witness
    assert _sorted_index_templates("xs", ws) == []  # ambiguous -> refuse


def test_bool_expected_refuses_distinct_count():
    # A bool expected is type-distinct from int (a count is a plain int), so a bool
    # contract refuses the distinct-count family — never coerced into a count.
    from app.execution.stub_synthesis import _distinct_count_pairs

    assert _distinct_count_pairs([("[1, 2]", "True"), ("[3, 4]", "False")]) is None


def test_int_arg_is_no_sorted_index():
    # double(2) == 4, double(5) == 10 is an INT contract: an int has no sorted()[k] and is
    # not a sequence, so the order-statistic family never contributes a body.
    from app.execution.stub_synthesis import _sorted_index_pairs, _sorted_index_templates

    assert _sorted_index_pairs([("2", "4"), ("5", "10")]) is None
    assert _sorted_index_templates("n", [("2", "4"), ("5", "10")]) == []


def test_no_witnesses_structural_view_mines_nothing():
    # With NO witness list (the structural view used by callers that gate elsewhere),
    # there is no literal to verify against, so neither family mines anything.
    from app.execution.stub_synthesis import (
        _distinct_count_applicable, _sorted_index_templates,
    )

    assert _sorted_index_templates("xs", []) == []
    assert _distinct_count_applicable([]) is False
    assert _distinct_count_applicable(None) is False


# --- FAKE-GREEN CANARY -------------------------------------------------------

def test_fake_green_canary_off_witness_rejects_wrong_sorted_index(tmp_path: Path):
    # The off-witness sequence canary is what keeps a wrong order statistic from passing as
    # green. On a PRE-SORTED contract first([1, 2, 3]) == 1, ([2, 4, 6]) == 2 the rival
    # xs[0] (a plain positional index) COINCIDES with sorted(xs)[0] (both == 1/2), so the
    # witnessed values alone cannot tell them apart. The canary's REVERSED probe (e.g.
    # [3, 2, 1] from [1, 2, 3]) splits them: sorted(xs)[0] == 1 there while xs[0] == 3 —
    # proving the off-witness probe rejects a body that merely coincides on the witnesses.
    from app.execution.stub_synthesis import _sequence_canary_probes

    witnesses = [(([1, 2, 3],), 1), (([2, 4, 6],), 2)]
    # both shapes coincide on the (pre-sorted) witnessed tuples:
    assert all(sorted(list(a))[0] == list(a)[0] for a, _e in witnesses)
    # the off-witness canary carries a probe where sorted(xs)[0] and xs[0] diverge:
    probes = [p[0] for p in _sequence_canary_probes(witnesses)]
    assert any(len(p) >= 1 and sorted(list(p))[0] != list(p)[0] for p in probes)


def test_sorted_index_holds_verifies_every_witness():
    # The in-family verification rejects an index that does not reproduce EVERY witness —
    # soundness comes from witness-verification, not from trusting the shape.
    from app.execution.stub_synthesis import _sorted_index_holds, _sorted_index_pairs

    pairs = _sorted_index_pairs(
        [("[3, 1, 2]", "2"), ("[5, 9, 1]", "5"), ("[8, 4, 6, 2]", "4")])
    assert _sorted_index_holds(1, pairs) is True   # the correct k
    assert _sorted_index_holds(0, pairs) is False  # min: 1/1/2 != 2/5/4
    assert _sorted_index_holds(-1, pairs) is False  # max: 3/9/8 != 2/5/4


# --- helper unit tests -------------------------------------------------------

def test_sorted_index_set_is_bounded_and_in_range():
    from app.execution.stub_synthesis import _sorted_index_set

    # shortest sequence length 2 -> only k in {-2, -1, 0, 1} in range for every witness.
    assert _sorted_index_set([([9, 1, 5], 5), ([7, 2], 7)]) == [-2, -1, 0, 1]
    # all length 3 -> range indices 0/1/2 plus the -1/-2 anchors -> [-2, -1, 0, 1, 2].
    assert _sorted_index_set([([3, 1, 2], 1), ([5, 9, 7], 5)]) == [-2, -1, 0, 1, 2]
    # no pairs -> empty (nothing to bound).
    assert _sorted_index_set([]) == []


def test_distinct_count_pairs_validation():
    from app.execution.stub_synthesis import _distinct_count_pairs

    # list args with varying int expected -> the parsed pairs.
    assert _distinct_count_pairs(
        [("[1, 2, 2]", "2"), ("[7, 8, 9]", "3")]) == [([1, 2, 2], 2), ([7, 8, 9], 3)]
    # all-equal expected ints collapse to a constant -> None.
    assert _distinct_count_pairs([("[1, 2, 2]", "2"), ("[5, 6]", "2")]) is None
    # a bool expected is type-distinct from int -> None.
    assert _distinct_count_pairs([("[1]", "True"), ("[2]", "False")]) is None
    # a non-sequence (int) arg -> None.
    assert _distinct_count_pairs([("2", "1"), ("5", "1")]) is None
    # a multi-arg witness -> None (this is a 1-arg family).
    assert _distinct_count_pairs([("[1], [2]", "2"), ("[3], [4]", "1")]) is None


def test_sorted_index_pairs_validation():
    from app.execution.stub_synthesis import _sorted_index_pairs

    # orderable list args with varying expected -> the parsed pairs.
    assert _sorted_index_pairs(
        [("[3, 1, 2]", "2"), ("[5, 9, 1]", "5")]) == [([3, 1, 2], 2), ([5, 9, 1], 5)]
    # all-equal expected collapse to a constant -> None.
    assert _sorted_index_pairs([("[3, 1, 2]", "1"), ("[5, 9, 1]", "1")]) is None
    # an unorderable/mixed sequence -> None.
    assert _sorted_index_pairs([("[1, 'a']", "1"), ("[2, 'b']", "2")]) is None
    # a non-sequence (int) arg -> None.
    assert _sorted_index_pairs([("2", "4"), ("5", "10")]) is None
    # a multi-arg witness -> None (this is a 1-arg family).
    assert _sorted_index_pairs([("[1], [2]", "1"), ("[3], [4]", "2")]) is None
