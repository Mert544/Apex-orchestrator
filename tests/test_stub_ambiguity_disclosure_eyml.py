"""Ambiguity DISCLOSURE for implement-stub — say WHY an ambiguous stub was
refused, and HOW to fix it, WITHOUT changing what lands.

When a stub's pinned witnesses are AMBIGUOUS (≥2 competing template bodies
satisfy every witness but diverge on an untested input), Apex correctly REFUSES
(lands nothing, never-fake-green). Before this wave the buyer got silence. Now
the refusal carries a deterministic, human-readable reason naming BOTH competing
shapes, a concrete discriminating input, and each shape's value there — pointing
at the witness to add.

The moat invariants these tests pin:
  * the ambiguous stub still lands NOTHING (the refuse DECISION is unchanged —
    the disclosure is purely additive);
  * the reason names BOTH competing bodies AND a concrete discriminating input;
  * adding the discriminating witness the reason points at lets the real body
    LAND and removes the reason (the disclosure pointed at a genuine fix);
  * a stub that lands cleanly emits NO reason;
  * same fixtures ⇒ byte-identical reason (deterministic, offline, zero-token).

The disclosure rides the plan's EXISTING ``blockers`` channel, which
``objective_compiler`` records into ``CompileResult.blocked`` (rendered under
"Blocked" / carried into the develop-session report) — an established refusal
surface, not a new cross-cutting one.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.objectives.implement_stub import plan_implement_stub
from app.execution.stub_synthesis import (
    AmbiguityDiagnosis,
    ambiguity_reason,
    find_stub_functions,
    pinned_test_files,
    render_ambiguity_reason,
)


# --- fixtures ----------------------------------------------------------------

def _suite_project(root: Path) -> Path:
    """A minimal importable project (``app`` package + ``tests`` dir) so the
    pinned-test linkage and the gated apply behave exactly as in production."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[build-system]\nrequires = []\n", encoding="utf-8")
    return root


def _write_stub(root: Path, module: str, src: str, test_src: str) -> str:
    """Write a stub module + its pinned test file; return the module rel path."""
    (root / "app" / module).write_text(src, encoding="utf-8")
    (root / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    return f"app/{module}"


def _reason_for(root: Path, module_rel: str, func: str) -> str | None:
    stub = next(s for s in find_stub_functions(
        (root / module_rel).read_text(encoding="utf-8")) if s.name == func)
    return ambiguity_reason(root, pinned_test_files(root, module_rel, func), stub)


# --- AMBIGUOUS min-vs-last: refused, both shapes + a discriminating input -----

_MIN_LAST_SRC = "def lowest_price(prices):\n    raise NotImplementedError\n"
_MIN_LAST_TESTS = (
    "from app.m import lowest_price\n"
    "def test():\n"
    "    assert lowest_price([3, 9, 2]) == 2\n"
    "    assert lowest_price([10, 1]) == 1\n")


def test_min_vs_last_still_lands_nothing(tmp_path: Path):
    # The field repro: min(prices) and prices[-1] both satisfy [3,9,2]->2 and
    # [10,1]->1 yet diverge off-witness, so Apex refuses — NOTHING lands.
    _suite_project(tmp_path)
    rel = _write_stub(tmp_path, "m.py", _MIN_LAST_SRC, _MIN_LAST_TESTS)
    original = (tmp_path / rel).read_text(encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), rel)
    assert not plan.new_contents  # refused — the refuse decision is unchanged
    assert (tmp_path / rel).read_text(encoding="utf-8") == original  # untouched


def test_min_vs_last_discloses_both_shapes_and_input(tmp_path: Path):
    # The refusal now carries a reason naming BOTH competing bodies AND a concrete
    # discriminating input — surfaced on the plan's EXISTING blockers channel.
    _suite_project(tmp_path)
    rel = _write_stub(tmp_path, "m.py", _MIN_LAST_SRC, _MIN_LAST_TESTS)
    plan = plan_implement_stub(str(tmp_path), rel)
    assert len(plan.blockers) == 1
    reason = plan.blockers[0]
    assert reason.startswith("lowest_price: ")
    # Both competing shapes are named.
    assert "min(prices)" in reason and "prices[-1]" in reason
    # A concrete discriminating input is shown, with each shape's value there.
    assert "differ on prices=" in reason
    assert "add a discriminating test" in reason


def test_min_vs_last_discriminating_input_actually_discriminates(tmp_path: Path):
    # The disclosed input must be one where the two shapes genuinely DIFFER (not a
    # witness): the reason is grounded in a real divergence, not a guess.
    _suite_project(tmp_path)
    rel = _write_stub(tmp_path, "m.py", _MIN_LAST_SRC, _MIN_LAST_TESTS)
    diagnosis = _diagnosis_for(tmp_path, rel, "lowest_price")
    assert diagnosis is not None
    seq = diagnosis.canary[0]
    assert min(seq) != seq[-1]  # min and last genuinely diverge on this input
    assert diagnosis.values[0] != diagnosis.values[1]


def _diagnosis_for(root: Path, module_rel: str,
                   func: str) -> AmbiguityDiagnosis | None:
    from app.execution.stub_synthesis import _ambiguity_diagnosis

    stub = next(s for s in find_stub_functions(
        (root / module_rel).read_text(encoding="utf-8")) if s.name == func)
    return _ambiguity_diagnosis(
        root, pinned_test_files(root, module_rel, func), stub)


def test_min_vs_last_refused_end_to_end(tmp_path: Path):
    # End-to-end through the gated apply: the ambiguous body must NOT land. The
    # refuse decision is unchanged; the disclosure is purely additive and never
    # makes anything land (or un-land).
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    rel = _write_stub(tmp_path, "m.py", _MIN_LAST_SRC, _MIN_LAST_TESTS)
    original = (tmp_path / rel).read_text(encoding="utf-8")
    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed
    assert (tmp_path / rel).read_text(encoding="utf-8") == original  # untouched


def test_disclosure_blocker_does_not_suppress_a_landing(tmp_path: Path):
    # A module with a fillable sibling (add) AND an ambiguous one (lowest_price):
    # add must still LAND. The disclosure rides the blockers channel, which
    # objective_compiler treats as a veto — so it is attached ONLY on the pure
    # empty-refusal branch (no new_contents). A plan that lands a body therefore
    # carries NO disclosure blocker, guaranteeing the reason can never un-land a
    # fill. (The ambiguous sibling's reason still surfaces wherever that module is
    # refused on its own — see the single-stub tests above.)
    _suite_project(tmp_path)
    (tmp_path / "app" / "m.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n\n\n"
        "def lowest_price(prices):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_add.py").write_text(
        "from app.m import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_lp.py").write_text(_MIN_LAST_TESTS, encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "app/m.py")
    assert "return a + b" in (plan.new_contents.get("app/m.py") or "")  # add LANDS
    assert plan.blockers == []  # no veto-blocker on a landing plan (moat)


# --- DISAMBIGUATED: the pointed-at fix makes the real body LAND ---------------

def test_added_witness_lands_min_and_clears_reason(tmp_path: Path):
    # Adding [4, 2, 7]->2 (last != min) is exactly the discriminating test the
    # reason asks for: now ONLY min satisfies all witnesses, so it LANDS and the
    # ambiguity reason is gone — proving the disclosure pointed at a real fix.
    _suite_project(tmp_path)
    disambiguated = (
        "from app.m import lowest_price\n"
        "def test():\n"
        "    assert lowest_price([3, 9, 2]) == 2\n"
        "    assert lowest_price([10, 1]) == 1\n"
        "    assert lowest_price([4, 2, 7]) == 2\n")
    rel = _write_stub(tmp_path, "m.py", _MIN_LAST_SRC, disambiguated)
    plan = plan_implement_stub(str(tmp_path), rel)
    body = plan.new_contents.get(rel)
    assert body is not None and "return min(prices)" in body  # min now LANDS
    assert plan.blockers == []  # no ambiguity left to disclose
    assert _reason_for(tmp_path, rel, "lowest_price") is None


# --- a clean first-try landing emits NO reason -------------------------------

def test_clean_landing_emits_no_reason(tmp_path: Path):
    # add(2,3)==5, add(10,1)==11 pins exactly one shape (a + b): it lands cleanly,
    # so there is nothing ambiguous to disclose.
    _suite_project(tmp_path)
    rel = _write_stub(
        tmp_path, "a.py",
        "def add(a, b):\n    raise NotImplementedError\n",
        "from app.a import add\n"
        "def test():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n")
    plan = plan_implement_stub(str(tmp_path), rel)
    assert "return a + b" in (plan.new_contents.get(rel) or "")
    assert plan.blockers == []
    assert _reason_for(tmp_path, rel, "add") is None


# --- determinism -------------------------------------------------------------

def test_reason_string_is_deterministic(tmp_path: Path):
    # Same fixture twice ⇒ byte-identical reason (no clock/random anywhere).
    _suite_project(tmp_path)
    rel = _write_stub(tmp_path, "m.py", _MIN_LAST_SRC, _MIN_LAST_TESTS)
    a = plan_implement_stub(str(tmp_path), rel).blockers
    b = plan_implement_stub(str(tmp_path), rel).blockers
    assert a == b and len(a) == 1


# --- the is_big parity-vs-threshold case from _is_ambiguous's docstring -------

def test_is_big_parity_vs_threshold_refused_and_disclosed(tmp_path: Path):
    # The exact ambiguity in _is_ambiguous's own docstring: is_big(5)==False,
    # is_big(200)==True is matched by BOTH a threshold (n > 5) and parity
    # (n % 2 == 0), which disagree off-witness. Refused — and disclosed.
    _suite_project(tmp_path)
    original = "def is_big(n):\n    raise NotImplementedError\n"
    rel = _write_stub(
        tmp_path, "b.py", original,
        "from app.b import is_big\n"
        "def test():\n"
        "    assert is_big(5) == False\n    assert is_big(200) == True\n")
    plan = plan_implement_stub(str(tmp_path), rel)
    assert not plan.new_contents  # refused — nothing lands
    assert (tmp_path / rel).read_text(encoding="utf-8") == original
    assert len(plan.blockers) == 1
    reason = plan.blockers[0]
    assert reason.startswith("is_big: ")
    assert "n % 2 == 0" in reason  # the parity shape
    assert "n >" in reason or "n <" in reason or "n >=" in reason  # a threshold
    assert "differ on n=" in reason and "add a discriminating test" in reason


# --- the pure renderer -------------------------------------------------------

def test_render_ambiguity_reason_is_pure_and_fixed():
    # The one-line renderer is a pure function of the diagnosis (no disk/tests):
    # it names both exprs, the named input, the two values, and the call to act.
    diagnosis = AmbiguityDiagnosis(
        exprs=("min(a)", "a[-1]"),
        params=("a",),
        canary=([3, 9, 2],),
        values=("2", "2"))
    line = render_ambiguity_reason(diagnosis)
    assert line == (
        "ambiguous: `min(a)` and `a[-1]` both satisfy the tests but differ on "
        "a=[3, 9, 2] (2 vs 2)… add a discriminating test")


def test_render_multi_arg_input_names_each_param():
    # A >=2-arg stub renders the discriminating input as name=value pairs in order.
    diagnosis = AmbiguityDiagnosis(
        exprs=("a % b", "a or b"),
        params=("a", "b"),
        canary=(5, 1),
        values=("0", "5"))
    line = render_ambiguity_reason(diagnosis)
    assert "differ on a=5, b=1 (0 vs 5)" in line


def test_non_ambiguous_contract_has_no_diagnosis(tmp_path: Path):
    # A genuine single-shape contract yields NO diagnosis (the guard is unchanged):
    # double(3)==6, double(4)==8 is matched only by a doubling shape.
    _suite_project(tmp_path)
    rel = _write_stub(
        tmp_path, "d.py",
        "def double(n):\n    raise NotImplementedError\n",
        "from app.d import double\n"
        "def test():\n    assert double(3) == 6\n    assert double(4) == 8\n")
    assert _reason_for(tmp_path, rel, "double") is None
    assert plan_implement_stub(str(tmp_path), rel).blockers == []
