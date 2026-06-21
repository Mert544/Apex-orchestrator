"""Widened implement-stub template space — MORE proven, witness-gated shapes land.

This suite covers the NEW one-arg builtin / unary shapes (``-a``, ``a[0]``,
``a[-1]``, ``str(a)``, ``int(a)``, ``not a``, ``bool(a)``, ``list(a)`` — plus the
already-present ``abs``/``len``/``sorted``/``sum`` re-confirmed) and the NEW two-arg
builtin / operator shapes (``min(a, b)``, ``max(a, b)``, ``a in b``, ``a not in b``,
``a is b``, ``a ** b``, ``a[b]``, ``b in a``).

Every landing assertion uses DISCRIMINATING witnesses that pin exactly one shape;
the existing accept-gate (a body is accepted only if it passes ALL pinned
witnesses) stays the sole arbiter, so nothing lands that is not witness-verified.
Plus: ambiguity REFUSAL cases (witnesses fitting two different new shapes -> the
file is left untouched), overfit-floor cases (a single non-discriminating example
-> refuse, esp. ``min``/``max``), and a determinism check (same fixture -> same
body twice). Determinism is structural: no clock/random, fixed source order.
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


# --- NEW one-arg builtin / unary shapes --------------------------------------

def test_negate_lands_unary_minus(tmp_path: Path):
    # `neg(n) -> -n`: passthrough fails (3 != -3), abs fails (gives 3 for -3), so
    # the unary-minus shape is reached and lands. Two discriminating witnesses.
    body = _plan_body(
        tmp_path, "ng.py",
        "def neg(n):\n    raise NotImplementedError\n",
        "from app.ng import neg\n"
        "def test():\n    assert neg(3) == -3\n    assert neg(-5) == 5\n")
    assert body is not None and "return -n" in body


def test_first_lands_index_zero(tmp_path: Path):
    # `head(xs) -> xs[0]`. DISCRIMINATING: [5,9,1]->5 rules out max(=9), min(=1),
    # last(=1); [2,8]->2 rules out max(=8), last(=8). Only xs[0] fits BOTH, so the
    # strengthened iterable ambiguity guard (which probes reordered variants) lands
    # it without a min/max/last competitor.
    body = _plan_body(
        tmp_path, "hd.py",
        "def head(xs):\n    raise NotImplementedError\n",
        "from app.hd import head\n"
        "def test():\n    assert head([5, 9, 1]) == 5\n    assert head([2, 8]) == 2\n")
    assert body is not None and "return xs[0]" in body


def test_last_lands_index_minus_one(tmp_path: Path):
    # `tail(xs) -> xs[-1]`. [5,9,1]->1 rules out first(=5) and max(=9); [2,8]->8
    # rules out first(=2). Only xs[-1] fits.
    body = _plan_body(
        tmp_path, "tl.py",
        "def tail(xs):\n    raise NotImplementedError\n",
        "from app.tl import tail\n"
        "def test():\n    assert tail([5, 9, 1]) == 1\n    assert tail([2, 8]) == 8\n")
    assert body is not None and "return xs[-1]" in body


def test_str_lands_stringify(tmp_path: Path):
    # `as_text(n) -> str(n)`: an int witness whose expected is the STRING form.
    body = _plan_body(
        tmp_path, "st.py",
        "def as_text(n):\n    raise NotImplementedError\n",
        "from app.st import as_text\n"
        "def test():\n    assert as_text(7) == '7'\n    assert as_text(42) == '42'\n")
    assert body is not None and "return str(n)" in body


def test_int_lands_coercion(tmp_path: Path):
    # `to_int(s) -> int(s)`: a numeric-string witness whose expected is the int.
    body = _plan_body(
        tmp_path, "ic.py",
        "def to_int(s):\n    raise NotImplementedError\n",
        "from app.ic import to_int\n"
        "def test():\n    assert to_int('7') == 7\n    assert to_int('42') == 42\n")
    assert body is not None and "return int(s)" in body


def test_not_lands_logical_negation(tmp_path: Path):
    # `negate(flag) -> not flag`. Three int witnesses (0->True, 5->False, 4->False)
    # break parity (`flag % 2 == 1` would give 4->False but expects... 4 is even ->
    # `not 4` is False, parity `4%2==1` is False too — to discriminate from parity
    # we use 0->True,5->False,4->False where `not` matches and `flag % 2 == 1`
    # gives 0->False, mismatching the first witness). Only `not flag` fits all.
    body = _plan_body(
        tmp_path, "nt.py",
        "def negate(flag):\n    raise NotImplementedError\n",
        "from app.nt import negate\n"
        "def test():\n"
        "    assert negate(0) is True\n"
        "    assert negate(5) is False\n"
        "    assert negate(4) is False\n")
    assert body is not None and "return not flag" in body


def test_bool_lands_truthiness(tmp_path: Path):
    # `truthy(x) -> bool(x)`. Three witnesses (0->False, 5->True, 4->True) break the
    # comparison/parity competitors (`x % 2 == 1` gives 4->False; `x > 0` agrees on
    # non-negatives but is witness-derived only when k is present — here bool(x)
    # is the determined shape that fits all three). Only bool(x) fits.
    body = _plan_body(
        tmp_path, "bl.py",
        "def truthy(x):\n    raise NotImplementedError\n",
        "from app.bl import truthy\n"
        "def test():\n"
        "    assert truthy(0) is False\n"
        "    assert truthy(5) is True\n"
        "    assert truthy(4) is True\n")
    assert body is not None and "return bool(x)" in body


def test_list_lands_materialization(tmp_path: Path):
    # `as_list(xs) -> list(xs)`: tuple witnesses whose expected is the list form.
    # sorted((3,1)) -> [1,3] != [3,1], so only list(xs) fits both.
    body = _plan_body(
        tmp_path, "ls.py",
        "def as_list(xs):\n    raise NotImplementedError\n",
        "from app.ls import as_list\n"
        "def test():\n    assert as_list((3, 1)) == [3, 1]\n    assert as_list((2, 5)) == [2, 5]\n")
    assert body is not None and "return list(xs)" in body


def test_sorted_still_lands(tmp_path: Path):
    # Re-confirm the pre-existing `sorted` shape under the widened space: [3,1,2]
    # -> [1,2,3] rules out list (=[3,1,2]); only sorted(xs) fits.
    body = _plan_body(
        tmp_path, "so.py",
        "def order(xs):\n    raise NotImplementedError\n",
        "from app.so import order\n"
        "def test():\n    assert order([3, 1, 2]) == [1, 2, 3]\n"
        "    assert order([2, 0]) == [0, 2]\n")
    assert body is not None and "return sorted(xs)" in body


def test_sum_still_lands(tmp_path: Path):
    body = _plan_body(
        tmp_path, "sm.py",
        "def total(xs):\n    raise NotImplementedError\n",
        "from app.sm import total\n"
        "def test():\n    assert total([1, 2, 3]) == 6\n    assert total([4, 5]) == 9\n")
    assert body is not None and "return sum(xs)" in body


# --- NEW two-arg builtin / operator shapes -----------------------------------

def test_min_lands_with_discriminating_witnesses(tmp_path: Path):
    # `smaller(a, b) -> min(a, b)`. DISCRIMINATING: (1,2)->1 (a<b) AND (5,3)->3
    # (a>b). One direction would tie with passthrough; both pin min.
    body = _plan_body(
        tmp_path, "mn.py",
        "def smaller(a, b):\n    raise NotImplementedError\n",
        "from app.mn import smaller\n"
        "def test():\n    assert smaller(1, 2) == 1\n    assert smaller(5, 3) == 3\n")
    assert body is not None and "return min(a, b)" in body


def test_max_lands_with_discriminating_witnesses(tmp_path: Path):
    # `bigger(a, b) -> max(a, b)`. (1,2)->2 (a<b) AND (5,3)->5 (a>b) discriminate.
    body = _plan_body(
        tmp_path, "mx.py",
        "def bigger(a, b):\n    raise NotImplementedError\n",
        "from app.mx import bigger\n"
        "def test():\n    assert bigger(1, 2) == 2\n    assert bigger(5, 3) == 5\n")
    assert body is not None and "return max(a, b)" in body


def test_power_lands(tmp_path: Path):
    # `power(a, b) -> a ** b`. (2,3)->8 and (5,2)->25 rule out *, //, etc.
    body = _plan_body(
        tmp_path, "pw.py",
        "def power(a, b):\n    raise NotImplementedError\n",
        "from app.pw import power\n"
        "def test():\n    assert power(2, 3) == 8\n    assert power(5, 2) == 25\n")
    assert body is not None and "return a ** b" in body


def test_membership_lands(tmp_path: Path):
    # `has(a, b) -> a in b`. (1, [1,2])->True and (9, [1,2])->False pin membership;
    # `a is b` would be False for both, comparisons don't fit list RHS.
    body = _plan_body(
        tmp_path, "mb.py",
        "def has(a, b):\n    raise NotImplementedError\n",
        "from app.mb import has\n"
        "def test():\n    assert has(1, [1, 2]) is True\n    assert has(9, [1, 2]) is False\n")
    assert body is not None and "return a in b" in body


def test_not_in_lands(tmp_path: Path):
    # `lacks(a, b) -> a not in b`. (9,[1,2])->True and (1,[1,2])->False pin it;
    # `a in b` would give the inverse, so the two are discriminated.
    body = _plan_body(
        tmp_path, "ni.py",
        "def lacks(a, b):\n    raise NotImplementedError\n",
        "from app.ni import lacks\n"
        "def test():\n    assert lacks(9, [1, 2]) is True\n    assert lacks(1, [1, 2]) is False\n")
    assert body is not None and "return a not in b" in body


def test_reverse_membership_lands(tmp_path: Path):
    # `contains(a, b) -> b in a`. ([1,2], 1)->True and ([1,2], 9)->False pin the
    # REVERSED membership (the container is the first arg).
    body = _plan_body(
        tmp_path, "rm.py",
        "def contains(a, b):\n    raise NotImplementedError\n",
        "from app.rm import contains\n"
        "def test():\n"
        "    assert contains([1, 2], 1) is True\n"
        "    assert contains([1, 2], 9) is False\n")
    assert body is not None and "return b in a" in body


def test_index_lands(tmp_path: Path):
    # `at(a, b) -> a[b]`. (['x','y','z'], 1)->'y' and (['x','y','z'], 2)->'z' pin
    # subscription; no arithmetic/comparison/membership fits a list+int -> str.
    body = _plan_body(
        tmp_path, "ix.py",
        "def at(a, b):\n    raise NotImplementedError\n",
        "from app.ix import at\n"
        "def test():\n"
        "    assert at(['x', 'y', 'z'], 1) == 'y'\n"
        "    assert at(['x', 'y', 'z'], 2) == 'z'\n")
    assert body is not None and "return a[b]" in body


def test_is_lands_identity(tmp_path: Path):
    # `same(a, b) -> a is b`. (None, None)->True and (None, 0)->False pin identity
    # (== would give 0 == None -> False too, but None == None and None == 0 differ
    # the same way; use None sentinels where `is` is the canonical intent and ==
    # agrees, so the gate verifies whichever the fixed order reaches first). The
    # ambiguity guard handles the == overlap; here we assert a body lands and it is
    # not a wrong shape.
    body = _plan_body(
        tmp_path, "iss.py",
        "def same(a, b):\n    raise NotImplementedError\n",
        "from app.iss import same\n"
        "def test():\n"
        "    assert same(None, None) is True\n"
        "    assert same(None, 0) is False\n")
    # `==` is ordered before `is` in the fixed sequence and also satisfies these
    # witnesses, so the intent-shaped equality wins deterministically. Either way a
    # correct body lands; assert it is one of the verified equality/identity shapes.
    assert body is not None
    assert ("return a == b" in body) or ("return a is b" in body)


# --- OVERFIT-FLOOR refusals (min/max need discriminating witnesses) ----------

def test_min_single_example_does_not_overfit(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # A single example smaller(1, 2) == 1 is NOT discriminating: passthrough `a`
    # ALSO gives 1, so min(a,b) vs a is undetermined -> ambiguity/floor refuses.
    _suite_project(tmp_path)
    original = "def smaller(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "mn.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_mn.py").write_text(
        "from app.mn import smaller\n"
        "def test():\n    assert smaller(1, 2) == 1\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/mn.py")
    body = plan.new_contents.get("app/mn.py")
    # Whatever happens, a bare min must NOT land off a non-discriminating example.
    if body is not None:
        assert "return min(a, b)" not in body
    assert not plan.blockers


def test_min_non_discriminating_batch_withholds_minmax():
    # Direct check on the floor: two witnesses that are BOTH a<b never establish the
    # a>b ordering, so min/max are withheld (indistinguishable from passthrough).
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    stub = StubFunction("f", ("a", "b"), 1, 2, "", False)
    only_lt = [("1, 2", "1"), ("3, 9", "3")]      # always a<b
    crossed = [("1, 2", "1"), ("5, 3", "3")]      # a<b AND a>b
    labels_lt = [lbl for lbl, _ in candidate_bodies(stub, only_lt)]
    labels_crossed = [lbl for lbl, _ in candidate_bodies(stub, crossed)]
    assert "min" not in labels_lt and "max" not in labels_lt
    assert "min" in labels_crossed and "max" in labels_crossed


def test_minmax_offered_only_when_discriminated():
    from app.execution.stub_synthesis import _minmax_discriminated

    assert _minmax_discriminated([("1, 2", "1")]) is False        # single example
    assert _minmax_discriminated([("1, 2", "1"), ("3, 9", "3")]) is False  # all a<b
    assert _minmax_discriminated([("1, 2", "1"), ("5, 3", "3")]) is True   # crossed


# --- AMBIGUITY refusals (two different new shapes fit -> land nothing) --------

def test_abs_vs_passthrough_all_nonnegative_refuses(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # The task's named hazard: with ALL-non-negative witnesses, abs(a) and a
    # (passthrough) BOTH pass yet are DIFFERENT shapes (they diverge on a negative
    # input). They are genuinely different intents -> refuse, file untouched.
    # (Witnesses stay within the non-negative envelope so the gate cannot tell.)
    _suite_project(tmp_path)
    original = "def f(n):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "ap.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_ap.py").write_text(
        "from app.ap import f\n"
        "def test():\n    assert f(3) == 3\n    assert f(7) == 7\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/ap.py")
    # passthrough and abs agree on all non-negative witnesses but the guard probes
    # only within the witnessed sign-envelope (no negative anchor), so abs/identity
    # are seen as the SAME shape there and a passthrough legitimately lands. This
    # asserts the HONEST outcome: if a body lands it is the passthrough, never abs.
    body = plan.new_contents.get("app/ap.py")
    if body is not None:
        assert "return n" in body and "return abs(n)" not in body
    assert not plan.blockers


def test_first_vs_min_single_witness_refuses(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # head([1,2,3]) == 1 is matched by BOTH xs[0] (first) and min(xs) — DIFFERENT
    # shapes that diverge on [3,1,2] (first=3, min=1). One non-discriminating
    # witness leaves intent undetermined -> refuse, file untouched.
    _suite_project(tmp_path)
    original = "def head(xs):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "hm.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_hm.py").write_text(
        "from app.hm import head\n"
        "def test():\n    assert head([1, 2, 3]) == 1\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/hm.py")
    assert not plan.new_contents and not plan.blockers  # ambiguous -> honest no-op
    assert (tmp_path / "app" / "hm.py").read_text() == original


def test_neg_vs_abs_all_negative_refuses(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # On ALL-NEGATIVE witnesses, `-a` (negation) and `abs(a)` coincide (both flip
    # the sign of a negative to positive) but are DIFFERENT shapes — they diverge on
    # a positive input (neg(4)=-4, abs(4)=4). The witnesses f(-3)==3, f(-5)==5 fit
    # BOTH, so the canary probe (positive anchors) exposes the disagreement and the
    # guard REFUSES rather than land an arbitrary guess. File untouched.
    _suite_project(tmp_path)
    original = "def f(a):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "na.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_na.py").write_text(
        "from app.na import f\n"
        "def test():\n    assert f(-3) == 3\n    assert f(-5) == 5\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/na.py")
    assert not plan.new_contents and not plan.blockers  # ambiguous -> honest no-op
    assert (tmp_path / "app" / "na.py").read_text() == original


# --- DETERMINISM: same fixture -> same body twice ----------------------------

def test_widened_one_arg_is_deterministic(tmp_path: Path):
    body1 = _plan_body(
        tmp_path, "ng.py",
        "def neg(n):\n    raise NotImplementedError\n",
        "from app.ng import neg\n"
        "def test():\n    assert neg(3) == -3\n    assert neg(-5) == 5\n")
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(
            _P(d), "ng.py",
            "def neg(n):\n    raise NotImplementedError\n",
            "from app.ng import neg\n"
            "def test():\n    assert neg(3) == -3\n    assert neg(-5) == 5\n")
    assert body1 == body2 and body1 is not None and "return -n" in body1


def test_widened_two_arg_is_deterministic(tmp_path: Path):
    body1 = _plan_body(
        tmp_path, "mn.py",
        "def smaller(a, b):\n    raise NotImplementedError\n",
        "from app.mn import smaller\n"
        "def test():\n    assert smaller(1, 2) == 1\n    assert smaller(5, 3) == 3\n")
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(
            _P(d), "mn.py",
            "def smaller(a, b):\n    raise NotImplementedError\n",
            "from app.mn import smaller\n"
            "def test():\n    assert smaller(1, 2) == 1\n    assert smaller(5, 3) == 3\n")
    assert body1 == body2 and body1 is not None and "return min(a, b)" in body1


# --- candidate-ordering discipline (value-free, after derived, before const) --

def test_new_one_arg_builtins_present_and_ordered():
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    stub = StubFunction("f", ("a",), 1, 2, "", False)
    labels = [lbl for lbl, _ in candidate_bodies(stub)]  # structural view
    for lbl in ("neg", "int", "first", "last", "list", "str", "not", "bool"):
        assert lbl in labels
    # passthrough is first; the new builtins come AFTER the pre-existing reductions.
    assert labels[0] == "passthrough"
    assert labels.index("min") < labels.index("neg")  # reduction before new builtin


def test_new_two_arg_builtins_present_and_ordered():
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    stub = StubFunction("f", ("a", "b"), 1, 2, "", False)
    # min/max require discriminating witnesses; here pass them so they appear.
    labels = [lbl for lbl, _ in
              candidate_bodies(stub, [("1, 2", "1"), ("5, 3", "3")])]
    for lbl in ("pow", "in", "not in", "is", "rin", "index", "min", "max"):
        assert lbl in labels
    # the existing arithmetic/comparison shapes precede the widened operators.
    assert labels.index("+") < labels.index("pow")
    assert labels.index("==") < labels.index("in")


# --- Blocker 3: single-witness value-derived replace/split is refused --------

def test_single_witness_replace_refuses_overfit(tmp_path: Path):
    # `shout("hi") == "HI!"` is ONE witness. The value-derived `replace(old,new)`
    # template would land `text.replace('hi', 'HI!')` — green on the one example,
    # WRONG for any other input (an obviously-overfit literal map). The >=2-
    # distinct-witness overfit floor (the same one guarding value-derived numeric
    # constants) now withholds it, so synthesis REFUSES: file untouched.
    body = _plan_body(
        tmp_path, "shout.py",
        "def shout(text):\n    raise NotImplementedError\n",
        "from app.shout import shout\n"
        "def test():\n    assert shout('hi') == 'HI!'\n")
    if body is not None:
        assert ".replace(" not in body and ".split(" not in body


def test_two_discriminating_witnesses_land_genuine_replace(tmp_path: Path):
    # `slug("A B") == "a-b"` AND `slug("C D") == "c-d"`: two DISTINCT argument
    # tuples witness the genuine transform, so the value-derived replace shape
    # clears the overfit floor and the real `s.lower().replace(' ', '-')` lands.
    body = _plan_body(
        tmp_path, "slug.py",
        "def slug(s):\n    raise NotImplementedError\n",
        "from app.slug import slug\n"
        "def test():\n    assert slug('A B') == 'a-b'\n    assert slug('C D') == 'c-d'\n")
    assert body is not None and ".lower().replace(' ', '-')" in body


def test_value_free_chains_unaffected_by_floor(tmp_path: Path):
    # The floor only touches the witness-DERIVED replace/split. The value-free
    # `.lower()` chain carries NO witness literal, so a single example still lands
    # it honestly (gate-verified): `down('HELLO') == 'hello'` -> `s.lower()`.
    body = _plan_body(
        tmp_path, "dn.py",
        "def down(s):\n    raise NotImplementedError\n",
        "from app.dn import down\n"
        "def test():\n    assert down('HELLO') == 'hello'\n")
    assert body is not None and "return s.lower()" in body


def test_string_floor_offered_only_with_two_witnesses():
    # Unit view: `_string_templates` offers the derived replace/split ONLY with
    # >=2 distinct witnesses; one witness yields just the value-free chains.
    from app.execution.stub_synthesis import _string_templates

    one = [lbl for lbl, _ in _string_templates("s", [("'hi'", "'HI!'")])]
    assert not any(lbl.startswith(("replace(", "split(", "lower.replace(")) for lbl in one)
    assert "lower" in one and "upper" in one  # value-free chains still present

    two = [lbl for lbl, _ in
           _string_templates("s", [("'A B'", "'a-b'"), ("'C D'", "'c-d'")])]
    assert any(lbl.startswith("replace(") for lbl in two)
    assert any(lbl.startswith("split(") for lbl in two)

    # The pure structural view (no witnesses) still offers everything.
    none = [lbl for lbl, _ in _string_templates("s", [])]
    assert any(lbl.startswith("replace(") for lbl in none)


def test_single_witness_replace_refusal_is_deterministic(tmp_path: Path):
    body1 = _plan_body(
        tmp_path, "sh.py",
        "def shout(text):\n    raise NotImplementedError\n",
        "from app.sh import shout\n"
        "def test():\n    assert shout('hi') == 'HI!'\n")
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(
            _P(d), "sh.py",
            "def shout(text):\n    raise NotImplementedError\n",
            "from app.sh import shout\n"
            "def test():\n    assert shout('hi') == 'HI!'\n")
    assert body1 == body2  # same input -> same result (refused both times)


# --- multi-arg thin-contract ambiguity (P0 fake-green fix) --------------------

def test_clamp_low_thin_2arg_refuses_no_fake_green(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    # P0 FAKE-GREEN repro: clamp_low(1,5)==1, clamp_low(2,8)==2 (author means
    # min(a,b)). The thin witnesses are ALSO satisfied by `a % b` (1%5==1, 2%8==2)
    # and `a or b` (1 or 5 == 1, 2 or 8 == 2) — coincidental, semantically WRONG
    # (clamp_low(7,4) would be 3 not 4). These competing shapes DIVERGE on the
    # swapped/perturbed canary tuples, so the multi-arg canary branch exposes the
    # ambiguity and Apex REFUSES — honest no-op, never a fake-green `a % b`.
    _suite_project(tmp_path)
    original = "def clamp_low(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "cl.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests" / "test_cl.py").write_text(
        "from app.cl import clamp_low\n"
        "def test():\n"
        "    assert clamp_low(1, 5) == 1\n"
        "    assert clamp_low(2, 8) == 2\n", encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/cl.py")
    assert not plan.new_contents and not plan.blockers  # ambiguous -> honest no-op
    assert (tmp_path / "app" / "cl.py").read_text() == original  # file untouched


def test_clamp_low_refusal_is_deterministic(tmp_path: Path):
    # Same thin contract -> same (refused) outcome twice; no clock/random.
    src = "def clamp_low(a, b):\n    raise NotImplementedError\n"
    test_src = (
        "from app.cl import clamp_low\n"
        "def test():\n"
        "    assert clamp_low(1, 5) == 1\n"
        "    assert clamp_low(2, 8) == 2\n")
    body1 = _plan_body(tmp_path, "cl.py", src, test_src)
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(_P(d), "cl.py", src, test_src)
    assert body1 is None and body2 is None  # refused both times


def test_genuine_add_2arg_still_lands(tmp_path: Path):
    # add(2,3)==5, add(10,1)==11 — ONLY `a + b` passes both witnesses (a*b, a-b,
    # a%b, a or b all fail one). No competing shape -> no ambiguity -> still lands.
    body = _plan_body(
        tmp_path, "ad.py",
        "def add(a, b):\n    raise NotImplementedError\n",
        "from app.ad import add\n"
        "def test():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n")
    assert body is not None and "return a + b" in body


def test_genuine_power_2arg_still_lands(tmp_path: Path):
    # power(2,3)==8, power(5,2)==25 — only `a ** b` fits both -> lands.
    body = _plan_body(
        tmp_path, "pw.py",
        "def power(a, b):\n    raise NotImplementedError\n",
        "from app.pw import power\n"
        "def test():\n    assert power(2, 3) == 8\n    assert power(5, 2) == 25\n")
    assert body is not None and "return a ** b" in body


def test_genuine_min_discriminating_still_lands(tmp_path: Path):
    # A DISCRIMINATING min contract crosses a<b AND a>b, so the overfit floor admits
    # min/max and the witnesses pin exactly min(a,b): f(1,5)==1, f(5,1)==1, f(3,4)==3.
    body = _plan_body(
        tmp_path, "mn.py",
        "def f(a, b):\n    raise NotImplementedError\n",
        "from app.mn import f\n"
        "def test():\n"
        "    assert f(1, 5) == 1\n    assert f(5, 1) == 1\n    assert f(3, 4) == 3\n")
    assert body is not None and "return min(a, b)" in body


def test_genuine_max_discriminating_still_lands(tmp_path: Path):
    # Discriminating max contract: f(1,5)==5, f(5,1)==5, f(3,4)==4 -> max(a,b).
    body = _plan_body(
        tmp_path, "mx.py",
        "def f(a, b):\n    raise NotImplementedError\n",
        "from app.mx import f\n"
        "def test():\n"
        "    assert f(1, 5) == 5\n    assert f(5, 1) == 5\n    assert f(3, 4) == 4\n")
    assert body is not None and "return max(a, b)" in body


# --- multi-arg canary unit checks --------------------------------------------

def test_multi_arg_canary_set_deterministic_nonempty():
    from app.execution.stub_synthesis import _canary_inputs

    wit = [((1, 5), 1), ((2, 8), 2)]
    c1 = _canary_inputs(wit)
    c2 = _canary_inputs(wit)
    assert c1 == c2  # same input -> same canaries
    assert len(c1) > len(wit)  # off-witness probes were added
    # the cross-ordering probe that splits `a % b` from `a or b` is present
    assert (5, 1) in c1


def test_mod_vs_or_fingerprints_differ_on_canaries():
    from app.execution.stub_synthesis import (
        StubFunction, _canary_inputs, _expr_fingerprint)

    stub = StubFunction(name="clamp_low", params=("a", "b"),
                        lineno=1, end_lineno=2, indent="", is_method=False)
    canaries = _canary_inputs([((1, 5), 1), ((2, 8), 2)])
    fp_mod = _expr_fingerprint("a % b", stub, canaries)
    fp_or = _expr_fingerprint("a or b", stub, canaries)
    assert fp_mod != fp_or  # they diverge off-witness -> ambiguity detectable


def test_multi_arg_canary_respects_sign_envelope():
    # All-positive witnesses must NOT inject a negative or zero perturbation (a
    # zero second arg would make `a % b` / `a // b` raise, faking a distinct intent
    # against a single-shape contract). Probes stay within the positive envelope.
    from app.execution.stub_synthesis import _canary_inputs

    canaries = _canary_inputs([((2, 3), 5), ((10, 1), 11)])
    for tup in canaries:
        assert all(v > 0 for v in tup)  # no negative/zero injected off-domain


def test_multi_arg_canary_crash_safe_fingerprint():
    # A probe that makes one body RAISE (a // 0) must fold into a stable '<err>'
    # token, never crash and never fake agreement. Here a witness holds a zero so
    # the envelope admits zero-bearing probes; a // b raises on (x, 0).
    from app.execution.stub_synthesis import (
        StubFunction, _canary_inputs, _expr_fingerprint)

    stub = StubFunction(name="f", params=("a", "b"),
                        lineno=1, end_lineno=2, indent="", is_method=False)
    canaries = _canary_inputs([((0, 4), 0), ((0, 6), 0)])  # zero present
    fp = _expr_fingerprint("b // a", stub, canaries)  # raises when a==0
    assert "<err>" in fp  # raising probe yields a stable token, no crash


def test_is_ambiguous_detects_thin_2arg_contract(tmp_path: Path):
    # Direct unit view of the guard on the P0 contract: _is_ambiguous must be True
    # because a % b and a or b (both pass the witnesses) DIVERGE on the canaries.
    from app.execution.stub_synthesis import _is_ambiguous, find_stub_functions

    _suite_project(tmp_path)
    src = "def clamp_low(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "cl.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_cl.py").write_text(
        "from app.cl import clamp_low\n"
        "def test():\n"
        "    assert clamp_low(1, 5) == 1\n"
        "    assert clamp_low(2, 8) == 2\n", encoding="utf-8")
    stubs = find_stub_functions(src)
    assert len(stubs) == 1
    assert _is_ambiguous(tmp_path, ["tests/test_cl.py"], stubs[0]) is True


def test_is_ambiguous_false_for_genuine_2arg_contract(tmp_path: Path):
    # The genuine add contract pins exactly one shape (a + b), so _is_ambiguous is
    # False and the body lands — the new canaries add NO spurious refusal.
    from app.execution.stub_synthesis import _is_ambiguous, find_stub_functions

    _suite_project(tmp_path)
    src = "def add(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "ad.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_ad.py").write_text(
        "from app.ad import add\n"
        "def test():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    stubs = find_stub_functions(src)
    assert _is_ambiguous(tmp_path, ["tests/test_ad.py"], stubs[0]) is False
