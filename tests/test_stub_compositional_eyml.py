"""1-arg BOUNDED 1-LEVEL COMPOSITIONAL family for implement-stub synthesis.

This suite covers the NEW 1-arg compositional shapes: ``return a[k] <op> c`` (a
constant index followed by a scalar arithmetic op) and ``return len(a) <op> c`` (a
length followed by the same), for the ONE composition that reproduces EVERY witness's
expected int. ``double_first([5, 9]) == 10, double_first([0, 1]) == 0,
double_first([7]) == 14`` lands ``return xs[0] * 2`` — the COMPOSITION ``xs[0] * 2``,
a body neither the constant-index atom nor the scalar-arith atom can spell ALONE. The
arg may be a ``str`` / ``list`` / ``tuple`` (it must support ``[k]`` and ``len``); the
expected value is a plain ``int``, type-exact for the accept-gate.

The composition REUSES the existing sound atoms: the constant index ``a[k]`` over a
BOUNDED index set (only indices valid for the shortest witnessed sequence, plus
``0``/``1``/``-1``) and ``len(a)``, fused with the scalar-arith ``(op, c)`` derivation
— ``op`` in ``{+, -, *}`` only (NO ``/``, NO ``**`` — locked refusals). EVERY candidate
body is VERIFIED to reproduce ALL witnesses before emit, so soundness comes from
witness-verification, not from trusting the composition; the existing type-exact
accept-gate and the off-witness str / sequence canary probes stay the sole arbiters, so
nothing lands that is not witness-verified and unambiguous (never-fake-green).

Plus: the expected ints must VARY (an all-equal contract collapses to a constant another
family owns, refused here); the >=2-distinct-witness overfit floor; an out-of-range
index for some witness is simply not a candidate (never an exception); the identity
``+ 0`` / ``* 1`` are never offered so a composition never shadows a simpler atom that
already fit; the body is emitted ONLY when it is the UNIQUE survivor, so when TWO
distinct ``(k, op, c)`` both reproduce every witness the family REFUSES rather than
guess; and a determinism check.
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


# --- LANDED: the unique witnessed composition --------------------------------

def test_double_first_index_times_const_lands(tmp_path: Path):
    # double_first([5, 9]) == 10, ([0, 1]) == 0, ([7]) == 14 -> xs[0] * 2. The body is a
    # COMPOSITION (constant index THEN scalar arith) that neither atom spells alone; it is
    # the unique (k, op, c) reproducing every witness, mined and VERIFIED end-to-end. The
    # [7] -> 14 witness pins the multiplier 2; the degenerate [0, 1] -> 0 (0 * 2 == 0) is
    # consistent with it, so 2 lands unambiguously.
    body = _plan_body(
        tmp_path, "df.py",
        "def double_first(xs):\n    raise NotImplementedError\n",
        "from app.df import double_first\n"
        "def test():\n"
        "    assert double_first([5, 9]) == 10\n"
        "    assert double_first([0, 1]) == 0\n"
        "    assert double_first([7]) == 14\n")
    assert body is not None and "return xs[0] * 2" in body


def test_index_one_plus_const_lands(tmp_path: Path):
    # g([10, 5]) == 6, ([0, 20]) == 21, ([3, 7, 9]) == 8 -> xs[1] + 1. The interior index 1
    # followed by a +1 offset is the unique survivor (xs[1] values 5/20/7 + 1 == 6/21/8),
    # a composition no single atom spells. The +/- spellings collapse to one additive
    # family, so xs[1] + 1 (never the equal xs[1] - -1) lands without spurious ambiguity.
    body = _plan_body(
        tmp_path, "g.py",
        "def g(xs):\n    raise NotImplementedError\n",
        "from app.g import g\n"
        "def test():\n"
        "    assert g([10, 5]) == 6\n"
        "    assert g([0, 20]) == 21\n"
        "    assert g([3, 7, 9]) == 8\n")
    assert body is not None and "return xs[1] + 1" in body


def test_len_times_const_lands(tmp_path: Path):
    # area('ab') == 6, ('abcd') == 12, ('a') == 3 -> len(s) * 3. The length atom fused with
    # the *3 multiplier is the unique survivor (lengths 2/4/1 * 3 == 6/12/3); len returns a
    # real int, type-exact for the gate. A composition no value-free reduction can spell.
    body = _plan_body(
        tmp_path, "ln.py",
        "def area(s):\n    raise NotImplementedError\n",
        "from app.ln import area\n"
        "def test():\n"
        "    assert area('ab') == 6\n"
        "    assert area('abcd') == 12\n"
        "    assert area('a') == 3\n")
    assert body is not None and "return len(s) * 3" in body


def test_len_plus_const_lands(tmp_path: Path):
    # pad('ab') == 5, ('abcd') == 7, ('a') == 4 -> len(s) + 3. The length atom fused with a
    # +3 offset is the unique survivor (lengths 2/4/1 + 3 == 5/7/4); the additive family is
    # represented once, so len(s) + 3 lands cleanly.
    body = _plan_body(
        tmp_path, "pd.py",
        "def pad(s):\n    raise NotImplementedError\n",
        "from app.pd import pad\n"
        "def test():\n"
        "    assert pad('ab') == 5\n"
        "    assert pad('abcd') == 7\n"
        "    assert pad('a') == 4\n")
    assert body is not None and "return len(s) + 3" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "df.py").write_text(
        "def double_first(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_df.py").write_text(
        "from app.df import double_first\n"
        "def test():\n"
        "    assert double_first([5, 9]) == 10\n"
        "    assert double_first([0, 1]) == 0\n"
        "    assert double_first([7]) == 14\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/df.py").new_contents.get("app/df.py")
    again = plan_implement_stub(str(tmp_path), "app/df.py").new_contents.get("app/df.py")
    assert first is not None and "return xs[0] * 2" in first
    assert first == again


# --- NO-SHADOW: a composition never overrides a simpler atom -----------------

def test_pure_index_atom_not_shadowed(tmp_path: Path):
    # second([1, 2, 3]) == 2, ([5, 9, 1]) == 9 is a PURE atom (xs[1]); the composition must
    # NOT shadow it with xs[1] + 0 / xs[1] * 1 — the identity offset/factor is never
    # offered, so the simpler atom xs[1] wins. A composition only adds NEW value, never
    # overrides a simpler body that already fit.
    body = _plan_body(
        tmp_path, "sd.py",
        "def second(xs):\n    raise NotImplementedError\n",
        "from app.sd import second\n"
        "def test():\n"
        "    assert second([1, 2, 3]) == 2\n"
        "    assert second([5, 9, 1]) == 9\n")
    assert body is not None and "return xs[1]" in body
    assert "xs[1] + 0" not in body and "xs[1] * 1" not in body


# --- REFUSALS ----------------------------------------------------------------

def test_division_op_refused(tmp_path: Path):
    # half_first([10, 2]) == 5, ([20, 4]) == 10, ([8, 1]) == 4 needs xs[0] / 2 — but `/` is
    # a LOCKED refusal (only +, -, * compose), so no compositional body is mined. Whatever
    # value-free shape (if any) the gate lands, it is NEVER a `/` composition.
    body = _plan_body(
        tmp_path, "hf.py",
        "def half_first(xs):\n    raise NotImplementedError\n",
        "from app.hf import half_first\n"
        "def test():\n"
        "    assert half_first([10, 2]) == 5\n"
        "    assert half_first([20, 4]) == 10\n"
        "    assert half_first([8, 1]) == 4\n")
    assert body is None or ("/" not in body)


def test_power_op_refused(tmp_path: Path):
    # sq_first([2, 0]) == 4, ([3, 0]) == 9, ([4, 0]) == 16 needs xs[0] ** 2 — but `**` is a
    # LOCKED refusal, and no +, -, * with a single constant reproduces 4/9/16 from 2/3/4
    # (the offsets 2/6/12 differ, the factors 2/3/4 differ). The family refuses rather than
    # bake a `**` it does not own.
    body = _plan_body(
        tmp_path, "sq.py",
        "def sq_first(xs):\n    raise NotImplementedError\n",
        "from app.sq import sq_first\n"
        "def test():\n"
        "    assert sq_first([2, 0]) == 4\n"
        "    assert sq_first([3, 0]) == 9\n"
        "    assert sq_first([4, 0]) == 16\n")
    assert body is None or ("**" not in body)


def test_single_witness_floor_refused():
    # A LONE double_first([5, 9]) == 10 is a single example: the >=2-distinct-witness floor
    # withholds the witness-DERIVED composition (one example could pin an arbitrary (k, op,
    # c) wrong for the next input). The structural template-miner emits no compositional
    # body from a single example.
    from app.execution.stub_synthesis import _compose_index_arith_templates

    assert _compose_index_arith_templates("xs", [("[5, 9]", "10")]) == []


def test_non_varying_all_same_output_refused():
    # double_first([5, 1]) == 10, ([5, 2]) == 10 has CONSTANT expected ints (all 10): a
    # composition that is the same for every input collapses to a constant another family
    # owns, so this family refuses it rather than baking a coincidental (k, op, c).
    from app.execution.stub_synthesis import _compose_index_arith_templates

    assert _compose_index_arith_templates(
        "xs", [("[5, 1]", "10"), ("[5, 2]", "10")]) == []


def test_out_of_range_index_is_no_candidate():
    # An index that is out of range for SOME witness is simply NOT a candidate (never an
    # exception). With witnesses [5, 9, 100] -> 300 and [7] -> 21, the shortest sequence has
    # length 1, so only k in {0, -1} are in range for EVERY witness; index 2 (valid only for
    # the longer one) is excluded, and the surviving body is the in-range xs[-1] * 3.
    from app.execution.stub_synthesis import (
        _compose_index_arith_templates, _compose_index_set, _compose_witness_pairs,
    )

    ws = [("[5, 9, 100]", "300"), ("[7]", "21")]
    pairs = _compose_witness_pairs(ws)
    assert pairs is not None
    assert _compose_index_set(pairs) == [-1, 0]  # index 2 dropped (oob for [7])
    assert _compose_index_arith_templates("xs", ws) == [("compose", "xs[-1] * 3")]


def test_ambiguous_two_compositions_fit_refused():
    # f([1, 1]) == 4, ([2, 2]) == 5 is reproduced by THREE distinct indices — xs[0] + 3,
    # xs[1] + 3 AND xs[-1] + 3 all give (4, 5) — so the witnesses cannot tell which index is
    # meant. The outputs VARY (4 != 5), so it is past the constant floor; the family REFUSES
    # rather than guess (never-fake-green).
    from app.execution.stub_synthesis import _compose_index_arith_templates

    assert _compose_index_arith_templates(
        "xs", [("[1, 1]", "4"), ("[2, 2]", "5")]) == []


def test_int_arg_is_no_composition():
    # double(2) == 4, double(5) == 10 is an INT contract: an int has no [k] / len, and this
    # family mines only str / list / tuple args, so it never contributes a body (n * 2 lands
    # via the scalar-arith atom instead). No composition is mined from an int arg.
    from app.execution.stub_synthesis import _compose_index_arith_templates

    assert _compose_index_arith_templates("n", [("2", "4"), ("5", "10")]) == []


def test_bool_expected_is_no_composition():
    # A bool expected is type-distinct from int (a scalar-arith result is a plain int), so a
    # bool contract refuses the whole family — never coerced into a composition.
    from app.execution.stub_synthesis import _compose_witness_pairs

    assert _compose_witness_pairs([("[1, 2]", "True"), ("[3, 4]", "False")]) is None


def test_no_witnesses_structural_view_mines_nothing():
    # With NO witness list (the pure structural view used by callers that gate elsewhere),
    # there is no expected int to verify against, so nothing is mined.
    from app.execution.stub_synthesis import _compose_index_arith_templates

    assert _compose_index_arith_templates("xs", []) == []


# --- FAKE-GREEN CANARY -------------------------------------------------------

def test_fake_green_canary_off_witness_rejects_wrong_composition():
    # The off-witness sequence canary is what keeps a wrong (k, op, c) from passing as green.
    # For the xs[0] * 2 contract on [2, 9] -> 4, [3, 8] -> 6, the cross-family rival
    # min(xs) * 2 coincides on the witnesses (xs[0] IS the min there: 2 and 3), so the
    # witnessed values alone cannot tell xs[0] * 2 from min(xs) * 2. The canary's REVERSED
    # probe (e.g. [9, 2] from [2, 9]) splits them: xs[0] * 2 == 18 there while min(xs) * 2
    # == 4 — proving the off-witness probe rejects the wrong body. Only the witness-true
    # xs[0] * 2 (verified against every witness) survives.
    from app.execution.stub_synthesis import _sequence_canary_probes

    pairs = [([2, 9], 4), ([3, 8], 6)]
    # xs[0] * 2 is witness-true; the rival min(xs) * 2 coincides on the witnessed tuples.
    assert all(xs[0] * 2 == e for xs, e in pairs)
    assert all(min(xs) * 2 == e for xs, e in pairs)  # rival coincides on witnesses
    # the off-witness canary carries a probe where the truth and the rival diverge.
    witnesses = [(([2, 9],), 4), (([3, 8],), 6)]
    probes = [p[0] for p in _sequence_canary_probes(witnesses)]
    assert any(len(p) == 2 and p[0] * 2 != min(p) * 2 for p in probes)


# --- helper unit tests -------------------------------------------------------

def test_compose_index_arith_templates_pick_unique():
    from app.execution.stub_synthesis import _compose_index_arith_templates

    # double_first: the unique xs[0] * 2 -> exactly the one body.
    assert _compose_index_arith_templates(
        "xs", [("[5, 9]", "10"), ("[0, 1]", "0"), ("[7]", "14")],
    ) == [("compose", "xs[0] * 2")]
    # len(s) + 3 on str args -> one body.
    assert _compose_index_arith_templates(
        "s", [("'ab'", "5"), ("'abcd'", "7"), ("'a'", "4")],
    ) == [("compose", "len(s) + 3")]
    # three indices (0, 1, -1) all fit + 3 -> ambiguous, refuse.
    assert _compose_index_arith_templates(
        "xs", [("[1, 1]", "4"), ("[2, 2]", "5")]) == []
    # all-equal expected -> a constant, refuse.
    assert _compose_index_arith_templates(
        "xs", [("[5, 1]", "10"), ("[5, 2]", "10")]) == []
    # a single witness (floor not met) -> refuse.
    assert _compose_index_arith_templates("xs", [("[5, 9]", "10")]) == []
    # a non-str/list/tuple arg -> refuse.
    assert _compose_index_arith_templates("n", [("2", "4"), ("5", "10")]) == []
    # no witnesses (structural view) -> nothing to mine.
    assert _compose_index_arith_templates("xs", []) == []


def test_compose_index_set_is_bounded_and_in_range():
    from app.execution.stub_synthesis import _compose_index_set

    # shortest sequence has length 1 -> only k in {0, -1} are in range for every witness.
    assert _compose_index_set([([5, 9, 100], 300), ([7], 21)]) == [-1, 0]
    # both length 2 -> indices 0, 1 (range), plus -1 anchor, all in range -> [-1, 0, 1].
    assert _compose_index_set([([10, 5], 6), ([0, 20], 21)]) == [-1, 0, 1]
    # no pairs -> empty (nothing to bound).
    assert _compose_index_set([]) == []


def test_compose_witness_pairs_validation():
    from app.execution.stub_synthesis import _compose_witness_pairs

    # list args with varying int expected -> the parsed pairs.
    assert _compose_witness_pairs(
        [("[5, 9]", "10"), ("[7]", "14")]) == [([5, 9], 10), ([7], 14)]
    # all-equal expected ints collapse to a constant -> None.
    assert _compose_witness_pairs([("[5]", "10"), ("[6]", "10")]) is None
    # a bool expected is type-distinct from int -> None.
    assert _compose_witness_pairs([("[5]", "True"), ("[6]", "False")]) is None
    # a non-str/list/tuple arg -> None.
    assert _compose_witness_pairs([("2", "4"), ("5", "10")]) is None
    # a multi-arg witness -> None (this is a 1-arg family).
    assert _compose_witness_pairs([("[1], [2]", "4"), ("[3], [4]", "5")]) is None


def test_compose_arith_atom_helpers():
    from app.execution.stub_synthesis import (
        _compose_add_offset, _compose_mul_factor,
    )

    # a consistent non-zero offset is returned; the identity 0 is not.
    assert _compose_add_offset([(5, 6), (20, 21)]) == 1
    assert _compose_add_offset([(2, 2), (9, 9)]) is None  # offset 0 -> bare atom
    assert _compose_add_offset([(5, 6), (20, 99)]) is None  # inconsistent -> refuse
    # a consistent non-unit factor is returned, deriving past a degenerate 0 * c == 0.
    assert _compose_mul_factor([(5, 10), (0, 0), (7, 14)]) == 2
    assert _compose_mul_factor([(2, 2), (9, 9)]) is None  # factor 1 -> bare atom
    assert _compose_mul_factor([(5, 10), (3, 6), (4, 13)]) is None  # 13 % 4 != 0
    assert _compose_mul_factor([(0, 0), (0, 0)]) is None  # all degenerate -> no factor
