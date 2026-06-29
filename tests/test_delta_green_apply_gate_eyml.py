"""DELTA-GREEN apply gate — Apex lands a correct change on a project whose suite
was ALREADY red on checkout (flaky / env / optional-dep / missing-data tests — the
real-world norm), WITHOUT weakening never-fake-green.

The field bug: Apex's verified-apply gate was ABSOLUTE-green — a change landed only
if the WHOLE suite returned 0. On a project with even one PRE-EXISTING failure
(unrelated to the change), a harmless contribution ran the suite, saw the
pre-existing red, and rolled back. So Apex landed NOTHING on the projects that need
it most. The repro was `assist "add docstrings" --target toml-0.10.2 --apply` →
"0 verified; 1 blocked" (toml has 2 pre-existing baseline failures from missing
sdist data).

The fix makes the gate DELTA-green: capture the SET of tests passing at baseline
(equivalently the failing-node set) ONCE per campaign and cache it; a change
VERIFIES iff every test that PASSED at baseline still passes (zero previously-green
tests newly fail). Pre-existing failures are TOLERATED; a true regression is STILL
blocked + rolled back.

These tests pin the CARDINAL invariant (a regression is never forgiven), the SET
semantics (a green test breaking is caught even if a different red one
coincidentally recovers — count alone would miss it), the new-collection-error
case (BLOCK), and the GREEN-baseline byte-identical guarantee (None baseline ⇒
absolute-green, so Apex's own green suite is unaffected).
"""

from __future__ import annotations

from pathlib import Path

from app.execution._apply_verify import (
    delta_green_disclosure,
    regressed_functions,
    run_full_suite_verification,
    suite_after_failing,
    suite_failing_nodes,
)
from app.execution.cross_file_rename import RenamePlan, apply_rename


# --- fixtures ----------------------------------------------------------------

def _edit_plan(rel: str, original: str, new: str) -> RenamePlan:
    plan = RenamePlan(old=rel, new="edit")
    plan.originals[rel] = original
    plan.new_contents[rel] = new
    plan.edits_by_file[rel] = 1
    return plan


def _red_baseline_project(root: Path) -> None:
    """A project with ONE modernizable green-covered module AND a pre-existing RED
    test unrelated to it (the env/missing-data failure shape Apex must tolerate).

    ``app/core.py`` has ``x == None`` (a behaviour-preserving modernize target) and
    a passing ``tests/test_core.py``. ``tests/test_env.py`` always FAILS (a
    pre-existing red, e.g. missing data) and never touches ``app/core.py``."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "core.py").write_text(
        "def f(x):\n    if x == None:\n        return 0\n    return x\n",
        encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(
        "from app.core import f\n\n"
        "def test_f():\n    assert f(None) == 0\n    assert f(3) == 3\n",
        encoding="utf-8")
    (root / "tests" / "test_env.py").write_text(
        "def test_pre_existing_red():\n"
        "    raise AssertionError('missing data — red before any change')\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")


# --- suite_after_failing: the comparable after-run ---------------------------

def test_suite_after_failing_returns_summary_and_nodes(tmp_path):
    _red_baseline_project(tmp_path)
    summary, failing = suite_after_failing(tmp_path)
    # The pre-existing red is observed; the after-run is byte-comparable to the
    # baseline capture (both use --continue-on-collection-errors).
    assert "tests/test_env.py::test_pre_existing_red" in failing
    assert getattr(summary, "commands", None)  # a real pytest run happened


def test_suite_failing_nodes_matches_after_failing_at_baseline(tmp_path):
    # The baseline capture and the after-run parse the SAME node ids on an
    # unchanged tree (so the diff is sound).
    _red_baseline_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    _summary, after = suite_after_failing(tmp_path)
    assert baseline == after
    assert baseline == frozenset({"tests/test_env.py::test_pre_existing_red"})


# --- delta_green_disclosure: the honest narrative fields ----------------------

def test_delta_green_disclosure_kept_change_reports_zero_introduced():
    base = frozenset({"t.py::test_red"})
    after = frozenset({"t.py::test_red"})  # the same red still red, nothing new
    d = delta_green_disclosure(base, after)
    assert d["delta_green"] is True
    assert d["baseline_failing"] == 1
    assert d["introduced"] == []


def test_delta_green_disclosure_names_a_regression():
    base = frozenset({"t.py::test_red"})
    after = frozenset({"t.py::test_red", "t.py::test_was_green"})
    d = delta_green_disclosure(base, after)
    assert d["introduced"] == ["t.py::test_was_green"]


# --- full-suite DELTA-GREEN: a harmless change LANDS on a red baseline --------

def test_full_suite_delta_green_lands_on_red_baseline(tmp_path):
    # The exact field bug in miniature: a behaviour-preserving change to a covered
    # module LANDS even though tests/test_env.py is red before any change.
    _red_baseline_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    assert baseline  # the baseline is genuinely RED

    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 0\n    return x\n")
    res = apply_rename(tmp_path, plan, verify=True, baseline_failing=baseline)

    assert res["applied"] is True
    assert res["verified"] is True            # no previously-green test broke
    assert res["rolled_back"] is False
    assert "is None" in (tmp_path / "app" / "core.py").read_text()  # the change held
    # Honest disclosure: the gate forgave the pre-existing red, introduced none.
    assert res["delta_green"]["baseline_failing"] == 1
    assert res["delta_green"]["introduced"] == []


def test_full_suite_pre_existing_red_still_red_after_landing(tmp_path):
    # never-fake-green: delta-green does NOT paper over the pre-existing failure —
    # it remains failing after the (correct) change lands.
    _red_baseline_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 0\n    return x\n")
    apply_rename(tmp_path, plan, verify=True, baseline_failing=baseline)
    _summary, after = suite_after_failing(tmp_path)
    assert "tests/test_env.py::test_pre_existing_red" in after  # still red, disclosed


# --- CARDINAL control: a change that breaks a GREEN test is STILL blocked -----

def test_cardinal_breaking_a_green_test_is_blocked_on_red_baseline(tmp_path):
    # The moat. Even on a red baseline (where delta-green forgives the pre-existing
    # red), a change that breaks a PREVIOUSLY-GREEN test must be rolled back.
    _red_baseline_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    # This rewrite BREAKS test_core (f(None) would now return 1, not 0).
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 1\n    return x\n")
    res = apply_rename(tmp_path, plan, verify=True, baseline_failing=baseline)

    assert res["applied"] is False
    assert res["rolled_back"] is True
    assert res["verified"] is False
    assert (tmp_path / "app" / "core.py").read_text() == before  # fully restored
    # The disclosure names the regression that caused the block.
    assert "tests/test_core.py::test_f" in res["delta_green"]["introduced"]


def test_cardinal_set_not_count_breaking_green_while_fixing_red_is_blocked(tmp_path):
    # The SET, not the count: a change that breaks a GREEN test AND coincidentally
    # makes a DIFFERENT pre-existing red one PASS keeps the failing COUNT equal (1
    # before, 1 after) — a count check would WRONGLY allow it. The set comparison
    # catches the green→red transition and BLOCKS.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    # ``flag.py`` drives BOTH a currently-green test and a currently-red test.
    (tmp_path / "app" / "flag.py").write_text(
        "def value():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_flag.py").write_text(
        "from app.flag import value\n\n"
        "def test_green():\n    assert value() == 1\n\n"   # green now
        "def test_red():\n    assert value() == 2\n",       # red now
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")

    _available, baseline = suite_failing_nodes(tmp_path)
    assert baseline == frozenset({"tests/test_flag.py::test_red"})  # exactly one red

    before = (tmp_path / "app" / "flag.py").read_text()
    # Flip the return to 2: test_red goes green, test_green goes RED. Count stays 1.
    plan = _edit_plan("app/flag.py", before, "def value():\n    return 2\n")
    res = apply_rename(tmp_path, plan, verify=True, baseline_failing=baseline)

    assert res["applied"] is False and res["rolled_back"] is True
    assert "tests/test_flag.py::test_green" in res["delta_green"]["introduced"]
    assert (tmp_path / "app" / "flag.py").read_text() == before


def test_cardinal_introduced_collection_error_is_blocked(tmp_path):
    # A change that makes a covered module un-IMPORTABLE introduces a brand-new
    # collection ERROR node (absent at baseline) — a NEW breakage, not a pre-existing
    # failure — so it must BLOCK even on a red baseline.
    _red_baseline_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    # Syntactically broken body → tests/test_core.py can no longer import → ERROR.
    plan = _edit_plan("app/core.py", before, "def f(x):\n    return (\n")
    res = apply_rename(tmp_path, plan, verify=True, baseline_failing=baseline)

    assert res["applied"] is False and res["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_text() == before
    # The new collection error is charged as a regression (the introduced set is
    # non-empty); the pre-existing red alone would have been tolerated.
    assert res["delta_green"]["introduced"]


# --- GREEN-baseline BYTE-IDENTICAL: None baseline ⇒ absolute-green ------------

def _green_project(root: Path) -> None:
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "core.py").write_text(
        "def f(x):\n    if x == None:\n        return 0\n    return x\n",
        encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(
        "from app.core import f\n\n"
        "def test_f():\n    assert f(None) == 0\n    assert f(3) == 3\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")


def test_green_baseline_none_keeps_a_passing_change_no_delta_key(tmp_path):
    # baseline_failing=None ⇒ the ABSOLUTE-green path: a passing change lands and the
    # result carries NO delta_green key (byte-identical to before the feature).
    _green_project(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 0\n    return x\n")
    res = apply_rename(tmp_path, plan, verify=True)  # no baseline threaded
    assert res["applied"] is True and res["verified"] is True
    assert "delta_green" not in res  # absolute-green result shape unchanged


def test_green_baseline_none_rolls_back_a_breaking_change(tmp_path):
    # baseline_failing=None ⇒ a breaking change still rolls back, exactly as before.
    _green_project(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before, "def f(x):\n    return 999\n")
    res = apply_rename(tmp_path, plan, verify=True)
    assert res["applied"] is False and res["rolled_back"] is True
    assert "delta_green" not in res
    assert (tmp_path / "app" / "core.py").read_text() == before


def test_empty_baseline_set_is_treated_as_green(tmp_path):
    # An EMPTY frozenset (a caller that proved the baseline GREEN) is handled by the
    # gate as absolute-green: any after-failure is a regression. A passing change
    # lands; the disclosure shows zero tolerated failures.
    _green_project(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 0\n    return x\n")
    res = apply_rename(tmp_path, plan, verify=True, baseline_failing=frozenset())
    assert res["applied"] is True and res["verified"] is True
    assert res["delta_green"]["baseline_failing"] == 0


# --- run_full_suite_verification: green-baseline verdict is unchanged ---------

def test_run_full_suite_verification_none_vs_empty_same_green_verdict(tmp_path):
    # On a GREEN project, None (absolute-green) and an empty-set baseline
    # (delta-green with nothing to forgive) reach the SAME verified verdict — the
    # round-21 equivalence that keeps Apex's own green gating unaffected.
    _green_project(tmp_path)
    out_none: dict = {}
    assert run_full_suite_verification(tmp_path, out_none) is True
    out_empty: dict = {}
    assert run_full_suite_verification(
        tmp_path, out_empty, baseline_failing=frozenset()) is True
    assert out_none["verified"] is True and out_empty["verified"] is True


# --- end-to-end through compile_objective on a RED baseline -------------------

def test_compile_objective_delta_green_lands_on_red_baseline(tmp_path):
    # The buyer path: compile_objective captures the red baseline ONCE and lands the
    # behaviour-preserving modernize move despite the unrelated pre-existing red.
    _red_baseline_project(tmp_path)
    from app.engine.objective_compiler import compile_objective

    result = compile_objective(str(tmp_path), objective="modernize", apply=True,
                               verify=True)
    assert result.steps  # a move LANDED (would be empty under absolute-green)
    assert "is None" in (tmp_path / "app" / "core.py").read_text()
    # The pre-existing red is untouched (never papered over).
    _summary, after = suite_after_failing(tmp_path)
    assert "tests/test_env.py::test_pre_existing_red" in after


def test_compile_objective_delta_green_still_blocks_a_regression(tmp_path):
    # compile_objective with a caller-supplied red baseline must STILL roll back a
    # move that would break a previously-green test (never-fake-green end to end).
    # A move that breaks test_core can't be produced by a behaviour-preserving
    # objective, so we assert the gate directly via a hand-built regressing plan run
    # through the same campaign baseline the compiler would use.
    _red_baseline_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 7\n    return x\n")
    res = apply_rename(tmp_path, plan, verify=True, baseline_failing=baseline)
    assert res["applied"] is False and res["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_text() == before


# --- determinism -------------------------------------------------------------

def test_regressed_functions_diff_is_deterministic(tmp_path):
    # The gate's verdict is a pure function of the two node sets — same in, same out.
    base = frozenset({"t.py::test_red[1]"})
    after = frozenset({"t.py::test_red[2]", "t.py::test_new"})
    first = regressed_functions(base, after)
    second = regressed_functions(base, after)
    assert first == second == frozenset({"t.py::test_new"})
