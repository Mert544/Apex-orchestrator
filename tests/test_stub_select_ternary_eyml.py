"""2-arg TWO-WITNESS TERNARY family for implement-stub synthesis.

This suite covers the NEW 2-arg selector-ternary shape: ``return a if a <op> b
else b`` for ``op`` in ``<=``/``>=``/``==`` — offered right after the existing
``min(a, b)`` / ``max(a, b)`` builtins in the candidate order.

``<``/``>`` are DELIBERATELY never offered: ``a if a < b else b`` / ``a if a > b
else b`` are simply the ``min``/``max`` intent spelled a second way — adding them
would be pure duplication of an ALREADY-OFFERED shape.

THE DEFERRAL RULE (adversarial-review correction): on a TOTAL order
``a if a <= b else b`` agrees with ``min(a, b)`` everywhere, but on a PARTIAL
order (sets) they are DIFFERENT functions — on an incomparable pair ``min`` keeps
``a`` where the ternary falls to ``b``. So a comparable-set-witnessed ``min``
contract would see two genuinely divergent surviving candidates and the ambiguity
guard would REFUSE what used to land cleanly as ``min(a, b)``. Therefore
``select<=``/``select>=`` DEFER to the builtins: they are offered ONLY when the
corresponding ``min``/``max`` does NOT reproduce every witness
(:func:`_minmax_reproduces_all`) — i.e. only in territory the builtin cannot
serve, which is where the family's value is anyway (incomparable-pair contracts,
witnesses the builtin fails). ``==`` has no ``min``/``max`` analogue and carries
no deferral: ``a if a == b else b`` captures an "always return b unless exactly
equal" contract no prior 2-arg template could spell.

Covered: a clean ``==`` landing (new capability), the set-witnessed ``min``
regression pin (the exact adversarial repro — recombination canaries produce an
incomparable pair; deferral restores the base ``min(a, b)`` landing
byte-identically), a landing where ``select<=`` fires because ``min`` genuinely
fails a witness (deferral does not smother the family's own territory), min/max
regression pins, thin-contract deferral pins, the floor unit tests, unit tests
for the deferral helper, and a structural check that ``<``/``>`` are never
emitted.
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


def _plan(tmp_path: Path, module: str, src: str, test_src: str):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / module).write_text(src, encoding="utf-8")
    (tmp_path / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    return plan_implement_stub(str(tmp_path), f"app/{module}")


def _plan_body(tmp_path: Path, module: str, src: str, test_src: str) -> str | None:
    return _plan(tmp_path, module, src, test_src).new_contents.get(f"app/{module}")


# --- LANDED: a if a == b else b (new -- no min/max shadow) -------------------

def test_select_eq_lands_new_capability(tmp_path: Path):
    # coalesce(0, 5) == 5, coalesce(7, 5) == 5, coalesce(5, 5) == 5 -> a "always
    # return b unless a == b" contract. Falsy-a (0) eliminates `a and b`; truthy-a
    # with a != b (7, 5) eliminates `a or b`; min/max are OFFERED (the witnesses
    # cross both a<b and a>b) but FAIL verification (min/max here is never simply
    # 5), so the <=/>= deferral is moot (min does not reproduce the witnesses).
    # Only `a if a == b else b` reproduces all three -- lands cleanly, no
    # ambiguity, a shape no prior 2-arg template could spell.
    body = _plan_body(
        tmp_path, "co.py",
        "def coalesce(a, b):\n    raise NotImplementedError\n",
        "from app.co import coalesce\n"
        "def test():\n"
        "    assert coalesce(0, 5) == 5\n"
        "    assert coalesce(7, 5) == 5\n"
        "    assert coalesce(5, 5) == 5\n")
    assert body is not None and "return a if a == b else b" in body


# --- REGRESSION PIN: set-witnessed min lands (partial-order deferral) ---------

def test_set_witnessed_min_regression_pin(tmp_path: Path):
    # ADVERSARIAL-REVIEW REGRESSION PIN (red-first: refused before the deferral
    # fix): on a PARTIAL order (sets), min and the <=-ternary are NOT the same
    # function -- min keeps `a` on an incomparable pair where `a if a <= b else
    # b` falls to `b`. These subset-pair witnesses satisfy BOTH shapes, and the
    # cross-witness recombination canary ({1}, {3, 4}) is INCOMPARABLE, so
    # without deferral the two survive as genuinely divergent candidates and the
    # guard refuses a contract base landed cleanly as min(a, b). The deferral
    # rule (select<=/>= withheld whenever the corresponding min/max already
    # reproduces every witness) restores the base landing byte-identically.
    body = _plan_body(
        tmp_path, "pms.py",
        "def pick_min(a, b):\n    raise NotImplementedError\n",
        "from app.pms import pick_min\n"
        "def test():\n"
        "    assert pick_min({1}, {1, 2}) == {1}\n"
        "    assert pick_min({3, 4, 5}, {3, 4}) == {3, 4}\n")
    assert body == "def pick_min(a, b):\n    return min(a, b)\n"


def test_select_le_fires_where_min_fails_witnesses(tmp_path: Path):
    # Deferral must NOT smother the family in its OWN territory: the second
    # witness holds an INCOMPARABLE pair ({1, 2} vs {3}, disjoint) whose expected
    # is `b` -- min(a, b) keeps `a` there (fails the witness), so min cannot
    # serve this contract and the <=-ternary is the only shape that can (min/max
    # are also withheld by their own floor: no a>b witness exists).
    body = _plan_body(
        tmp_path, "slf.py",
        "def pick(a, b):\n    raise NotImplementedError\n",
        "from app.slf import pick\n"
        "def test():\n"
        "    assert pick({1}, {1, 2}) == {1}\n"
        "    assert pick({1, 2}, {3}) == {3}\n")
    assert body is not None and "return a if a <= b else b" in body


# --- REGRESSION PIN: min/max unaffected ---------------------------------------

def test_min_regression_pin_unaffected(tmp_path: Path):
    # smaller(1, 2) == 1 (a<b), smaller(5, 3) == 3 (a>b) -- DISCRIMINATING for
    # min. min reproduces every witness, so select<= DEFERS and min(a, b) lands,
    # byte-identical to before this family existed.
    body = _plan_body(
        tmp_path, "mm.py",
        "def smaller(a, b):\n    raise NotImplementedError\n",
        "from app.mm import smaller\n"
        "def test():\n"
        "    assert smaller(1, 2) == 1\n"
        "    assert smaller(5, 3) == 3\n")
    assert body == "def smaller(a, b):\n    return min(a, b)\n"


def test_max_regression_pin_unaffected(tmp_path: Path):
    # bigger(1, 2) == 2 (a<b), bigger(5, 3) == 5 (a>b) -- mirrors the min pin above.
    body = _plan_body(
        tmp_path, "mm2.py",
        "def bigger(a, b):\n    raise NotImplementedError\n",
        "from app.mm2 import bigger\n"
        "def test():\n"
        "    assert bigger(1, 2) == 2\n"
        "    assert bigger(5, 3) == 5\n")
    assert body == "def bigger(a, b):\n    return max(a, b)\n"


# --- DEFERRAL PINS: thin contracts min/max could serve stay base-identical ----

def test_thin_tie_contract_defers_and_restores_base_landing(tmp_path: Path):
    # pick(5, 5) == 5 (tie), pick(9, 3) == 3 (a>b, NO a<b -- min/max's own floor
    # stays unmet). min REPRODUCES both witnesses though, so select<= DEFERS
    # (before the deferral fix this refused as `a and b` vs select<= ambiguity --
    # itself a change from base, which landed `a and b` as the only match).
    # Deferral restores the base landing byte-identically.
    plan = _plan(
        tmp_path, "sel.py",
        "def pick(a, b):\n    raise NotImplementedError\n",
        "from app.sel import pick\n"
        "def test():\n"
        "    assert pick(5, 5) == 5\n"
        "    assert pick(9, 3) == 3\n")
    body = plan.new_contents.get("app/sel.py")
    assert body == "def pick(a, b):\n    return a and b\n"
    assert not plan.blockers


def test_select_eq_lands_where_le_defers(tmp_path: Path):
    # pick2(5, 5) == 5 (tie), pick2(0, -3) == -3 (falsy a -- eliminates
    # `a and b`), pick2(9, 3) == 3 (truthy a, a != b -- eliminates `a or b`).
    # min reproduces ALL THREE witnesses, so select<= DEFERS; == carries no
    # deferral (no min/max analogue) and is the ONLY matching candidate left --
    # lands `a if a == b else b` where base landed nothing (genuine new reach;
    # before the deferral fix this refused as select<= vs select== ambiguity).
    plan = _plan(
        tmp_path, "sel2.py",
        "def pick2(a, b):\n    raise NotImplementedError\n",
        "from app.sel2 import pick2\n"
        "def test():\n"
        "    assert pick2(5, 5) == 5\n"
        "    assert pick2(0, -3) == -3\n"
        "    assert pick2(9, 3) == 3\n")
    body = plan.new_contents.get("app/sel2.py")
    assert body is not None and "return a if a == b else b" in body
    assert not plan.blockers


def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE coalesce(0, 5) == 5 cannot discriminate ANY selector operator (only
    # one branch is ever witnessed) -- the floor withholds the whole family.
    body = _plan_body(
        tmp_path, "s1.py",
        "def coalesce1(a, b):\n    raise NotImplementedError\n",
        "from app.s1 import coalesce1\n"
        "def test():\n    assert coalesce1(0, 5) == 5\n")
    assert body is None or (
        "if a <= b" not in body and "if a >= b" not in body and "if a == b" not in body)


# --- helper unit tests: _select_discriminated / _select_ternary_templates ----

def test_select_discriminated_needs_both_branches():
    from app.execution.stub_synthesis import _select_discriminated

    assert _select_discriminated([], "<=") is False
    assert _select_discriminated([("1, 2", "1")], "<=") is False  # single witness
    # a tie ALONE only ever contributes the true branch -- never discriminates.
    assert _select_discriminated([("5, 5", "5")], "<=") is False
    # a tie (true) + a strict a>b (false) discriminates <=, even with NO a<b
    # anywhere -- the exact floor _minmax_discriminated cannot satisfy.
    assert _select_discriminated([("5, 5", "5"), ("9, 3", "3")], "<=") is True
    assert _select_discriminated([("5, 5", "5"), ("9, 3", "3")], ">=") is False
    assert _select_discriminated([("1, 2", "1"), ("5, 3", "3")], ">=") is True


def test_minmax_reproduces_all_drives_deferral():
    from app.execution.stub_synthesis import _minmax_reproduces_all

    # min reproduces the classic discriminating int witnesses -> defer.
    assert _minmax_reproduces_all([("1, 2", "1"), ("5, 3", "3")], "<=") is True
    # min FAILS the incomparable-pair witness (keeps a where b is expected) ->
    # no deferral, the ternary's own territory.
    assert _minmax_reproduces_all(
        [("{1}, {1, 2}", "{1}"), ("{1, 2}, {3}", "{3}")], "<=") is False
    # max analogue for >=.
    assert _minmax_reproduces_all([("1, 2", "2"), ("5, 3", "5")], ">=") is True
    assert _minmax_reproduces_all([("1, 2", "1"), ("5, 3", "5")], ">=") is False
    # an unorderable pair makes min/max RAISE -- territory it cannot serve.
    assert _minmax_reproduces_all([("1, 'x'", "'x'"), ("2, 'y'", "'y'")], "<=") is False
    # non-literal witnesses are skipped (nothing to evaluate either way).
    assert _minmax_reproduces_all([("X, Y", "1")], "<=") is True


def test_select_ternary_templates_deferral_and_eq():
    from app.execution.stub_synthesis import _select_ternary_templates

    # Tie (5, 5) + a>b (9, 3): <= and == are both discriminated, but min
    # REPRODUCES both witnesses so <= DEFERS; == has no min/max analogue and no
    # deferral -> only select== is emitted.
    out = _select_ternary_templates("a", "b", [("5, 5", "5"), ("9, 3", "3")])
    assert out == [("select==", "a if a == b else b")]
    # The incomparable-pair set witnesses: min fails a witness -> <= fires.
    out = _select_ternary_templates(
        "a", "b", [("{1}, {1, 2}", "{1}"), ("{1, 2}, {3}", "{3}")])
    assert out == [("select<=", "a if a <= b else b")]


def test_select_ternary_templates_no_witnesses_emits_nothing():
    from app.execution.stub_synthesis import _select_ternary_templates

    assert _select_ternary_templates("a", "b", []) == []


def test_lt_gt_never_offered_by_construction():
    # Structural guarantee, not just an empirical absence: probe many witness
    # shapes that discriminate every possible true/false branch combination -- not
    # one of them should ever emit a bare `<` or `>` selector ternary. Only
    # <=, >=, == are in the family's fixed operator set.
    from app.execution.stub_synthesis import _select_ternary_templates

    witness_sets = [
        [("5, 5", "5"), ("9, 3", "3")],       # tie + a>b, no a<b
        [("1, 2", "1"), ("5, 3", "3")],       # a<b + a>b (min/max-discriminating too)
        [("0, -3", "-3"), ("9, 3", "3"), ("5, 5", "5")],  # tie + two a>b
        [("2, 9", "2"), ("9, 2", "2")],       # a<b twice, contradictory expecteds
        [("{1}, {1, 2}", "{1}"), ("{1, 2}, {3}", "{3}")],  # partial-order territory
    ]
    allowed = {
        ("select<=", "a if a <= b else b"),
        ("select>=", "a if a >= b else b"),
        ("select==", "a if a == b else b"),
    }
    for witnesses in witness_sets:
        out = _select_ternary_templates("a", "b", witnesses)
        assert set(out) <= allowed
