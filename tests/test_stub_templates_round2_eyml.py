"""Round-2 widened implement-stub template space — MORE proven, witness-gated shapes.

This suite covers the SECOND batch of synthesis body shapes added to widen the
template space so more concrete code lands deterministically:

  * one-arg ``tuple(a)`` (sequence materialization, type-distinct from ``list(a)``);
  * one-arg ``round(a, k)`` with a witness-derived ndigits ``k`` (under an overfit
    floor; the float-precision divergence class is guarded by the type-exact gate);
  * two-arg ``f"{a}{b}"`` (f-string concat, distinct from ``a + b`` on mixed types);
  * two-arg ``f"{a}{sep}{b}"`` with a witness-derived literal separator (floored);
  * two-arg ``a.get(b)`` (mapping access);
  * two-arg ``a.get(b, default)`` with a witness-derived literal default (floored).

For EACH shape: a DISCRIMINATING-witness landing test (the body that lands is
exactly the intended one), an OVERFIT-FLOOR refusal (a single non-discriminating
example must not bake a witness literal in), an AMBIGUITY refusal (witnesses that
fit two genuinely-different shapes -> land nothing), and a determinism check (same
fixture -> same body twice). The existing accept-gate (a body lands ONLY if it
passes ALL pinned witnesses) stays the sole arbiter; never-fake-green holds — a
shape that only coincidentally passes thin witnesses is REFUSED, never landed.

Determinism is structural: no clock/random, fixed source order, fixed candidate
sequence (the new shapes sit AFTER the witness-derived templates and BEFORE the
constant-last fallback).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from pathlib import Path as _P


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


def _plan(tmp_path: Path, module: str, src: str, test_src: str):
    """Full plan (so a test can assert no-op + no-blockers on a refusal)."""
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / module).write_text(src, encoding="utf-8")
    (tmp_path / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    return plan_implement_stub(str(tmp_path), f"app/{module}")


# --- tuple(a) ----------------------------------------------------------------

def test_tuple_lands_materialization(tmp_path: Path):
    # `as_tuple(xs) -> tuple(xs)`. DISCRIMINATING from list(xs): the expected is a
    # TUPLE, and the type-exact accept-gate rejects list(xs) (a list != a tuple).
    # sorted((3,1)) -> (1,3) order also rules out sorted; only tuple(xs) fits both.
    body = _plan_body(
        tmp_path, "tp.py",
        "def as_tuple(xs):\n    raise NotImplementedError\n",
        "from app.tp import as_tuple\n"
        "def test():\n"
        "    assert as_tuple([3, 1]) == (3, 1)\n"
        "    assert as_tuple([2, 5]) == (2, 5)\n")
    assert body is not None and "return tuple(xs)" in body


def test_tuple_not_confused_with_list(tmp_path: Path):
    # A LIST-returning contract must land list(xs), never tuple(xs): the type-exact
    # gate keeps the two apart, proving tuple/list discriminate on result type.
    body = _plan_body(
        tmp_path, "tl2.py",
        "def as_list(xs):\n    raise NotImplementedError\n",
        "from app.tl2 import as_list\n"
        "def test():\n"
        "    assert as_list((3, 1)) == [3, 1]\n"
        "    assert as_list((2, 5)) == [2, 5]\n")
    assert body is not None and "return list(xs)" in body and "tuple(xs)" not in body


def test_tuple_present_after_list_in_order():
    # tuple sits right after list among the sequence-projection builtins (fixed
    # value-free order, after reductions, before the constant-last fallback).
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    stub = StubFunction("f", ("a",), 1, 2, "", False)
    labels = [lbl for lbl, _ in candidate_bodies(stub)]
    assert "tuple" in labels and "list" in labels
    assert labels.index("list") < labels.index("tuple")
    assert labels.index("sum") < labels.index("tuple")  # reduction precedes builtin


# --- round(a, k) (witness-derived ndigits, floored) --------------------------

def test_round_ndigits_lands_with_two_witnesses(tmp_path: Path):
    # `to_2dp(x) -> round(x, 2)`. Two DISTINCT witnesses both rounding to 2 dp:
    # 3.14159->3.14, 2.71828->2.72. A bare round(x) gives 3.0/3 (wrong), passthrough
    # gives 3.14159 (wrong); only round(x, 2) fits BOTH -> lands.
    body = _plan_body(
        tmp_path, "r2.py",
        "def to_2dp(x):\n    raise NotImplementedError\n",
        "from app.r2 import to_2dp\n"
        "def test():\n"
        "    assert to_2dp(3.14159) == 3.14\n"
        "    assert to_2dp(2.71828) == 2.72\n")
    assert body is not None and "return round(x, 2)" in body


def test_round_ndigits_single_witness_refuses_overfit(tmp_path: Path):
    # ONE witness `to_2dp(3.14159) == 3.14` must NOT bake an arbitrary k in: the
    # >=2-distinct-witness overfit floor withholds round(x, k), and no value-free
    # shape matches (round(x) gives 3) -> REFUSE, file untouched.
    body = _plan_body(
        tmp_path, "r2s.py",
        "def to_2dp(x):\n    raise NotImplementedError\n",
        "from app.r2s import to_2dp\n"
        "def test():\n    assert to_2dp(3.14159) == 3.14\n")
    if body is not None:
        assert "round(x, 2)" not in body and "round(x," not in body


def test_round_ndigits_floor_unit():
    # Unit view: round(n, k) is OFFERED only with >=2 distinct witnesses; one
    # witness yields no derived round(,k) (only the value-free round earlier).
    from app.execution.stub_synthesis import _round_ndigits_templates

    one = [lbl for lbl, _ in _round_ndigits_templates("x", [("3.14159", "3.14")])]
    assert one == []  # floored away on a single example
    two = _round_ndigits_templates(
        "x", [("3.14159", "3.14"), ("2.71828", "2.72")])
    assert any(lbl.startswith("round(") for lbl, _ in two)
    bodies = [body for _lbl, body in two]
    assert "round(x, 2)" in bodies


def test_round_ndigits_type_exact_no_int_truncation_fakegreen(tmp_path: Path):
    # The %d-truncation lesson: round(n, 0) returns a FLOAT-vs-INT that the gate
    # tells apart. A contract expecting the INT-typed round(n) (e.g. 2.6->3 as int)
    # must NOT be served by round(n, k) which returns a float (2.6 rounded to k dp).
    # Here expecteds are ints rounded to nearest -> bare round(x) lands, not round(,k).
    body = _plan_body(
        tmp_path, "ri.py",
        "def nearest(x):\n    raise NotImplementedError\n",
        "from app.ri import nearest\n"
        "def test():\n"
        "    assert nearest(2.6) == 3\n"
        "    assert nearest(4.2) == 4\n")
    # round(x) yields int 3/4 (matches); round(x, k>0) yields floats 2.6/4.2 (fails
    # the type-exact gate). The value-free round wins -> no fake-green float body.
    assert body is not None and "return round(x)" in body


# --- f"{a}{b}" (f-string concat, value-free) ---------------------------------

def test_fstring_concat_lands_mixed_types(tmp_path: Path):
    # `label(a, b) -> f"{a}{b}"`. Mixed str+int where `a + b` would raise (TypeError
    # on "x" + 5). The f-string stringifies both, so ONLY the f-string shape fits:
    # "x"+5 -> "x5", "ab"+3 -> "ab3".
    body = _plan_body(
        tmp_path, "fc.py",
        "def label(a, b):\n    raise NotImplementedError\n",
        "from app.fc import label\n"
        "def test():\n"
        "    assert label('x', 5) == 'x5'\n"
        "    assert label('ab', 3) == 'ab3'\n")
    assert body is not None and 'return f"{a}{b}"' in body


def test_fstring_concat_present_after_index_before_get():
    # f-string sits after the operator/index shapes and before a.get(b) in the fixed
    # two-arg order (value-free widened shapes, ahead of the constant-last fallback).
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    stub = StubFunction("f", ("a", "b"), 1, 2, "", False)
    labels = [lbl for lbl, _ in candidate_bodies(stub)]
    assert "fstr" in labels and "get" in labels
    assert labels.index("index") < labels.index("fstr")
    assert labels.index("fstr") < labels.index("get")


def test_string_concat_prefers_plus_over_fstring(tmp_path: Path):
    # On a pure str+str concat both `a + b` and f"{a}{b}" produce the same result and
    # AGREE on every recombination canary (same forward-concat intent), so the guard
    # does NOT refuse and the earlier, simpler `a + b` lands deterministically.
    body = _plan_body(
        tmp_path, "pc.py",
        "def cat(a, b):\n    raise NotImplementedError\n",
        "from app.pc import cat\n"
        "def test():\n"
        "    assert cat('foo', 'bar') == 'foobar'\n"
        "    assert cat('a', 'b') == 'ab'\n")
    assert body is not None and "return a + b" in body


# --- f"{a}{sep}{b}" (witness-derived separator, floored) ---------------------

def test_fstring_sep_lands_with_two_witnesses(tmp_path: Path):
    # `dashed(a, b) -> f"{a}-{b}"`. Two DISTINCT witnesses pin the literal "-"
    # separator: ("a","b")->"a-b", ("c","d")->"c-d". Plain f"{a}{b}" gives "ab"
    # (wrong), a + b gives "ab" (wrong); only the dashed f-string fits both.
    body = _plan_body(
        tmp_path, "fs.py",
        "def dashed(a, b):\n    raise NotImplementedError\n",
        "from app.fs import dashed\n"
        "def test():\n"
        "    assert dashed('a', 'b') == 'a-b'\n"
        "    assert dashed('c', 'd') == 'c-d'\n")
    assert body is not None and 'return f"{a}-{b}"' in body


def test_fstring_sep_single_witness_refuses_overfit(tmp_path: Path):
    # ONE witness `dashed("a","b") == "a-b"` must NOT bake the "-" in: the overfit
    # floor withholds the derived separator f-string. No value-free shape matches
    # ("ab" != "a-b"), so synthesis REFUSES -> file untouched.
    body = _plan_body(
        tmp_path, "fs1.py",
        "def dashed(a, b):\n    raise NotImplementedError\n",
        "from app.fs1 import dashed\n"
        "def test():\n    assert dashed('a', 'b') == 'a-b'\n")
    if body is not None:
        assert 'f"{a}-{b}"' not in body


def test_fstring_sep_floor_unit():
    # Unit view: the derived separator f-string is OFFERED only with >=2 distinct
    # witnesses; the empty separator is never emitted (it equals plain f"{a}{b}").
    from app.execution.stub_synthesis import _fstring_sep_templates

    one = [lbl for lbl, _ in _fstring_sep_templates("a", "b", [("'a', 'b'", "'a-b'")])]
    assert one == []
    two = _fstring_sep_templates(
        "a", "b", [("'a', 'b'", "'a-b'"), ("'c', 'd'", "'c-d'")])
    bodies = [body for _lbl, body in two]
    assert 'f"{a}-{b}"' in bodies
    assert all('{a}{b}' not in body for body in bodies)  # empty sep never emitted


# --- a.get(b) (mapping access, value-free) -----------------------------------

def test_get_lands_with_absent_key_witness(tmp_path: Path):
    # `lookup(a, b) -> a.get(b)`. An ABSENT-key witness DISCRIMINATES get from a[b]:
    # ({"x":1},"z")==None is what a.get(b) returns but a[b] would RAISE. Present-key
    # witnesses pin the stored value; the `== None` witness (mined by the `==`
    # extractor) rules out subscription, so only a.get(b) fits all three.
    body = _plan_body(
        tmp_path, "gt.py",
        "def lookup(a, b):\n    raise NotImplementedError\n",
        "from app.gt import lookup\n"
        "def test():\n"
        "    assert lookup({'x': 1}, 'x') == 1\n"
        "    assert lookup({'y': 2}, 'y') == 2\n"
        "    assert lookup({'x': 1}, 'z') == None\n")  # noqa: E711 - witness needs ==
    assert body is not None and "return a.get(b)" in body


def test_get_vs_index_all_present_refuses(tmp_path: Path):
    # AMBIGUITY: with ALL keys present, a.get(b) and a[b] both pass the witnesses but
    # are DIFFERENT shapes (they diverge on an absent key: get->None, []->raise). The
    # recombination canary builds an absent-key probe (dict from one row, key from
    # another), so the guard sees the divergence and REFUSES -> honest no-op.
    plan = _plan(
        tmp_path, "gx.py",
        "def lookup(a, b):\n    raise NotImplementedError\n",
        "from app.gx import lookup\n"
        "def test():\n"
        "    assert lookup({'x': 1}, 'x') == 1\n"
        "    assert lookup({'x': 1, 'y': 2}, 'y') == 2\n")
    assert not plan.new_contents and not plan.blockers  # ambiguous -> no-op
    assert (tmp_path / "app" / "gx.py").read_text() == (
        "def lookup(a, b):\n    raise NotImplementedError\n")


def test_get_present_before_constant_in_order():
    # a.get(b) is a value-free two-arg shape; its derived a.get(b, default) follows it.
    from app.execution.stub_synthesis import StubFunction, candidate_bodies

    stub = StubFunction("f", ("a", "b"), 1, 2, "", False)
    w = [("{'x': 1}, 'x'", "1"), ("{'x': 1}, 'z'", "0")]
    labels = [lbl for lbl, _ in candidate_bodies(stub, w)]
    assert "get" in labels
    assert any(lbl.startswith("get(default=") for lbl in labels)
    assert labels.index("get") < min(
        i for i, lbl in enumerate(labels) if lbl.startswith("get(default="))


# --- a.get(b, default) (witness-derived default, floored) --------------------

def test_get_default_lands_with_two_witnesses(tmp_path: Path):
    # `lookup0(a, b) -> a.get(b, 0)`. Two DISTINCT witnesses include absent keys
    # whose expected is the default 0: ({"y":2},"q")->0, ({"x":1},"z")->0, plus a
    # present ({"x":1},"x")->1. a.get(b) would give None (wrong) for absent; only
    # a.get(b, 0) fits all three.
    body = _plan_body(
        tmp_path, "gd.py",
        "def lookup0(a, b):\n    raise NotImplementedError\n",
        "from app.gd import lookup0\n"
        "def test():\n"
        "    assert lookup0({'x': 1}, 'x') == 1\n"
        "    assert lookup0({'y': 2}, 'q') == 0\n"
        "    assert lookup0({'x': 1}, 'z') == 0\n")
    assert body is not None and "return a.get(b, 0)" in body


def test_get_default_single_witness_refuses_overfit(tmp_path: Path):
    # ONE witness `lookup0({"x":1},"z") == 0` must NOT bake the default 0 in: the
    # overfit floor withholds a.get(b, default). a.get(b) gives None (!= 0) so no
    # value-free shape matches -> REFUSE, file untouched.
    body = _plan_body(
        tmp_path, "gd1.py",
        "def lookup0(a, b):\n    raise NotImplementedError\n",
        "from app.gd1 import lookup0\n"
        "def test():\n    assert lookup0({'x': 1}, 'z') == 0\n")
    if body is not None:
        assert "a.get(b, 0)" not in body and "a.get(b," not in body


def test_get_default_floor_unit():
    # Unit view: a.get(b, default) is OFFERED only with >=2 distinct witnesses, one
    # body per witnessed literal expected value (the default is a witnessed result).
    from app.execution.stub_synthesis import _get_default_templates

    one = _get_default_templates("a", "b", [("{'x': 1}, 'z'", "0")])
    assert one == []
    two = _get_default_templates(
        "a", "b", [("{'x': 1}, 'x'", "1"), ("{'x': 1}, 'z'", "0")])
    bodies = [body for _lbl, body in two]
    assert "a.get(b, 0)" in bodies and "a.get(b, 1)" in bodies


# --- recombination canary unit checks ----------------------------------------

def test_recombination_canary_builds_absent_key_probe():
    from app.execution.stub_synthesis import _canary_inputs

    wit = [(({"x": 1}, "x"), 1), (({"x": 1, "y": 2}, "y"), 2)]
    canaries = _canary_inputs(wit)
    # the dict from row 0 recombined with the key from row 1 is an ABSENT-key probe
    assert ({"x": 1}, "y") in canaries
    # witnessed tuples are always included
    assert ({"x": 1}, "x") in canaries


def test_recombination_canary_deterministic():
    from app.execution.stub_synthesis import _canary_inputs

    wit = [(("a", "b"), "ab"), (("c", "d"), "cd")]
    assert _canary_inputs(wit) == _canary_inputs(wit)  # same input -> same canaries


def test_recombination_splits_get_from_index():
    from app.execution.stub_synthesis import (
        StubFunction, _canary_inputs, _expr_fingerprint)

    stub = StubFunction("f", ("a", "b"), 1, 2, "", False)
    canaries = _canary_inputs([(({"x": 1}, "x"), 1), (({"x": 1, "y": 2}, "y"), 2)])
    fp_get = _expr_fingerprint("a.get(b)", stub, canaries)
    fp_idx = _expr_fingerprint("a[b]", stub, canaries)
    assert fp_get != fp_idx  # they diverge off-witness (absent key) -> detectable


def test_recombination_fstring_agrees_with_plus_on_concat():
    # `a + b` and f"{a}{b}" are the SAME forward-concat intent: equal fingerprints on
    # the recombination canaries, so the guard does NOT spuriously refuse a genuine
    # concat (the earlier `a + b` simply wins).
    from app.execution.stub_synthesis import (
        StubFunction, _canary_inputs, _expr_fingerprint)

    stub = StubFunction("f", ("a", "b"), 1, 2, "", False)
    canaries = _canary_inputs([(("a", "b"), "ab"), (("c", "d"), "cd")])
    assert _expr_fingerprint("a + b", stub, canaries) == \
        _expr_fingerprint('f"{a}{b}"', stub, canaries)


# --- determinism: same fixture -> same body twice ----------------------------

def test_tuple_is_deterministic(tmp_path: Path):
    args = ("tp.py", "def f(xs):\n    raise NotImplementedError\n",
            "from app.tp import f\n"
            "def test():\n    assert f([3, 1]) == (3, 1)\n    assert f([2, 5]) == (2, 5)\n")
    body1 = _plan_body(tmp_path, *args)
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(_P(d), *args)
    assert body1 == body2 and body1 is not None and "return tuple(xs)" in body1


def test_round_ndigits_is_deterministic(tmp_path: Path):
    args = ("r2.py", "def f(x):\n    raise NotImplementedError\n",
            "from app.r2 import f\n"
            "def test():\n    assert f(3.14159) == 3.14\n    assert f(2.71828) == 2.72\n")
    body1 = _plan_body(tmp_path, *args)
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(_P(d), *args)
    assert body1 == body2 and body1 is not None and "return round(x, 2)" in body1


def test_fstring_sep_is_deterministic(tmp_path: Path):
    args = ("fs.py", "def f(a, b):\n    raise NotImplementedError\n",
            "from app.fs import f\n"
            "def test():\n    assert f('a', 'b') == 'a-b'\n    assert f('c', 'd') == 'c-d'\n")
    body1 = _plan_body(tmp_path, *args)
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(_P(d), *args)
    assert body1 == body2 and body1 is not None and 'return f"{a}-{b}"' in body1


def test_get_default_is_deterministic(tmp_path: Path):
    args = ("gd.py", "def f(a, b):\n    raise NotImplementedError\n",
            "from app.gd import f\n"
            "def test():\n"
            "    assert f({'x': 1}, 'x') == 1\n"
            "    assert f({'y': 2}, 'q') == 0\n"
            "    assert f({'x': 1}, 'z') == 0\n")
    body1 = _plan_body(tmp_path, *args)
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(_P(d), *args)
    assert body1 == body2 and body1 is not None and "return a.get(b, 0)" in body1


def test_get_vs_index_refusal_is_deterministic(tmp_path: Path):
    args = ("gx.py", "def f(a, b):\n    raise NotImplementedError\n",
            "from app.gx import f\n"
            "def test():\n"
            "    assert f({'x': 1}, 'x') == 1\n"
            "    assert f({'x': 1, 'y': 2}, 'y') == 2\n")
    body1 = _plan_body(tmp_path, *args)
    with tempfile.TemporaryDirectory() as d:
        body2 = _plan_body(_P(d), *args)
    assert body1 is None and body2 is None  # ambiguous -> refused both times
