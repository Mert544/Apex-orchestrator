"""FIX: delta-green must not stamp ``verified`` when the delta comparison was
VACUOUS — the WHOLE scoped selection was already red/ERROR at baseline, so
nothing could regress AND no test actually exercised the changed code green.

Delta-green correctly TOLERATES pre-existing red (a move is not charged for
tests that were already failing). But when EVERY selected test was already
red/ERROR before the move, the diff is vacuous: the after-run can add no
newly-passing evidence, yet the move sailed through stamped as if a test
vouched for it. This is a LABELING honesty fix (mirrors ``TIER_PREVIEW`` /
``NO_SUITE``): the move still lands (delta-green semantics — no NEW failures
allowed — are unchanged), but its verification tier must read distinctly
(``DELTA_VACUOUS`` / ``TIER_BASELINE_RED``), never blended with a genuinely
test-vouched move.

Red-first: ``test_whole_suite_vacuous_delta_labeled_unverifiable``,
``test_scoped_delta_vacuous_when_whole_scope_red_at_baseline``,
``test_impact_scope_vacuous_delta_labeled_not_rolled_back``,
``test_compile_step_vacuous_tier_is_baseline_red_but_coverage_verified_untouched``,
and the render tests all FAIL on the pre-fix code (no ``delta_vacuous``
key/tier existed — the move read plain ``verified``/coverage-verified). The
partial-red and green-baseline tests PIN today's exact byte-identical
behaviour (they cannot be red-first — they assert nothing changed).

Two adversarial-review hardening fixes, also pinned here:

* ``CompileStep.coverage_verified`` stays UNCHANGED by ``delta_vacuous`` (it is
  a SHARED verdict ``app/agent/assist.py``'s auto-commit gate reads — see
  ``test_compile_step_vacuous_tier_is_baseline_red_but_coverage_verified_untouched``);
  the honest label is applied only in the label/render surfaces
  (``ds._tier_for``, ``_compile_tier_tag``, ``_compile_tier_counts``).
* ``passed_count_of_text`` reads the LAST ``"N passed"`` occurrence, not the
  first — a failing test's own captured stdout/stderr (printed BEFORE
  pytest's real tail summary line) can itself contain an earlier
  ``\\d+ passed``-shaped substring, which a first-match search would
  wrongly return instead of the true tail count
  (``test_passed_count_of_text_ignores_earlier_decoy_in_captured_output``,
  ``test_scoped_delta_vacuous_not_defeated_by_decoy_passed_substring``,
  ``test_verify_delta_green_vacuous_not_defeated_by_decoy_passed_substring``).
"""

from __future__ import annotations

from types import SimpleNamespace

from pathlib import Path

from app.engine import develop_session as ds
from app.engine.develop_session import SessionMove, SessionObjective, SessionReport
from app.engine.objective_compiler import (
    CompileResult,
    CompileStep,
    _compile_tier_counts,
    _compile_tier_tag,
    render_compile_markdown,
)
from app.execution import _apply_verify as av
from app.execution._apply_verify import (
    DELTA_VACUOUS,
    delta_vacuous,
    mark_delta_vacuous,
    passed_count_of_text,
    run_full_suite_verification,
    suite_failing_nodes,
)
from app.execution.cross_file_rename import RenamePlan, _scoped_delta_verdict, apply_rename


def _edit_plan(rel: str, original: str, new: str) -> RenamePlan:
    plan = RenamePlan(old=rel, new="edit")
    plan.originals[rel] = original
    plan.new_contents[rel] = new
    plan.edits_by_file[rel] = 1
    return plan


# --- pure predicate ------------------------------------------------------------

def test_delta_vacuous_true_only_when_scope_red_and_nothing_passed():
    assert delta_vacuous(frozenset({"t.py::x"}), 0) is True
    # Partial-red / genuinely-covered evidence: something passed -> not vacuous.
    assert delta_vacuous(frozenset({"t.py::x"}), 3) is False
    # Empty scope: nothing WAS entirely red (there was no scope) -> not vacuous.
    assert delta_vacuous(frozenset(), 0) is False


def test_delta_vacuous_is_deterministic():
    base = frozenset({"t.py::x", "t.py::y"})
    assert delta_vacuous(base, 0) == delta_vacuous(base, 0) is True


def test_passed_count_of_text_parses_tail_summary():
    assert passed_count_of_text("3 passed, 1 failed in 0.12s") == 3
    assert passed_count_of_text("1 failed in 0.01s") == 0
    assert passed_count_of_text("") == 0


def test_mark_delta_vacuous_overrides_level_and_is_additive():
    out = {"verification_strength": {"level": "function"}}
    mark_delta_vacuous(out)
    assert out["delta_vacuous"] is True
    assert out["verification_strength"]["level"] == DELTA_VACUOUS


def test_mark_delta_vacuous_called_twice_is_idempotent_and_deterministic():
    out1: dict = {}
    mark_delta_vacuous(out1)
    out2: dict = {}
    mark_delta_vacuous(out2)
    assert out1 == out2 == {
        "delta_vacuous": True,
        "verification_strength": {"level": DELTA_VACUOUS},
    }


# --- _verify_delta_green: whole-suite vacuous-delta labeling -------------------

def _all_red_project(root: Path) -> None:
    """A project whose ONE test is red at baseline and stays red — no test
    anywhere in the suite ever exercises the (behaviour-preserving) change to
    ``app/core.py`` green. The delta comparison over this scope is vacuous."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "core.py").write_text(
        "def f(x):\n    if x == None:\n        return 0\n    return x\n",
        encoding="utf-8")
    (root / "tests" / "test_always_red.py").write_text(
        "def test_always_red():\n"
        "    raise AssertionError('perpetually red — unrelated to app.core')\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")


def test_whole_suite_vacuous_delta_labeled_unverifiable(tmp_path):
    _all_red_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    assert baseline == frozenset({"tests/test_always_red.py::test_always_red"})

    before = (tmp_path / "app" / "core.py").read_text()
    after_src = "def f(x):\n    if x is None:\n        return 0\n    return x\n"
    (tmp_path / "app" / "core.py").write_text(after_src, encoding="utf-8")
    strength_inputs = (
        ["app/core.py"], {"app/core.py": before}, {"app/core.py": after_src})

    out: dict = {}
    kept = run_full_suite_verification(
        tmp_path, out, strength_inputs=strength_inputs, baseline_failing=baseline)

    assert kept is True
    assert out["verified"] is True  # broke nothing new — delta-green still holds
    # RED TODAY: pre-fix, neither key existed and the level read whatever
    # stamp_coverage_strength assessed (e.g. "none"), indistinguishable from a
    # genuinely test-vouched move.
    assert out["delta_vacuous"] is True
    assert out["verification_strength"]["level"] == DELTA_VACUOUS


def test_whole_suite_vacuous_delta_never_fires_without_strength_inputs(tmp_path):
    # The vacuous check runs regardless of whether strength_inputs was supplied
    # (move_module's caller passes None) — it must not silently skip labeling.
    _all_red_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    out: dict = {}
    kept = run_full_suite_verification(tmp_path, out, baseline_failing=baseline)
    assert kept is True
    assert out["delta_vacuous"] is True


# --- byte-identical pins: partial-red and green baseline -----------------------

def _partial_red_project(root: Path) -> None:
    """A red baseline where ONE test genuinely covers+passes the changed
    function and a SEPARATE, unrelated test is red — the established
    delta-green shape. The scope is NOT entirely red, so labeling must be
    untouched by this fix."""
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


def test_partial_red_baseline_keeps_todays_exact_labels(tmp_path):
    _partial_red_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    assert baseline == frozenset({"tests/test_env.py::test_pre_existing_red"})

    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 0\n    return x\n")
    res = apply_rename(tmp_path, plan, verify=True, baseline_failing=baseline)

    assert res["applied"] is True
    assert res["verified"] is True
    # BYTE-IDENTICAL PIN: no delta_vacuous key anywhere, and the coverage level
    # is the genuine one a covering test earned — unchanged by this fix.
    assert "delta_vacuous" not in res
    assert res["verification_strength"]["level"] != DELTA_VACUOUS
    assert res["coverage"] == "function"


def test_green_baseline_never_carries_delta_vacuous(tmp_path):
    _partial_red_project(tmp_path)
    # Delete the pre-existing red so the project is genuinely green, then run
    # the ABSOLUTE-green path (baseline_failing=None) — it never reaches
    # ``_verify_delta_green`` at all.
    (tmp_path / "tests" / "test_env.py").unlink()
    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before,
                      "def f(x):\n    if x is None:\n        return 0\n    return x\n")
    res = apply_rename(tmp_path, plan, verify=True)  # no baseline threaded
    assert res["applied"] is True and res["verified"] is True
    assert "delta_vacuous" not in res
    assert "delta_green" not in res  # unchanged absolute-green shape


# --- _scoped_delta_verdict: the impact-scoped per-move gate --------------------

def _plan() -> RenamePlan:
    return RenamePlan(old="app/core.py", new="edit")


def test_scoped_delta_vacuous_when_whole_scope_red_at_baseline():
    proc = SimpleNamespace(
        returncode=1,
        stdout=("FAILED tests/test_x.py::test_pre - boom\n"
                "0 passed, 1 failed in 0.01s"),
        stderr="")
    ok, evidence = _scoped_delta_verdict(
        proc, ["tests/test_x.py"], _plan(),
        frozenset({"tests/test_x.py::test_pre"}))
    assert ok is True
    assert evidence["delta_vacuous"] is True


def test_scoped_delta_not_vacuous_when_something_passed():
    proc = SimpleNamespace(
        returncode=1,
        stdout=("FAILED tests/test_x.py::test_pre - boom\n"
                "2 passed, 1 failed in 0.01s"),
        stderr="")
    ok, evidence = _scoped_delta_verdict(
        proc, ["tests/test_x.py"], _plan(),
        frozenset({"tests/test_x.py::test_pre"}))
    assert ok is True
    assert "delta_vacuous" not in evidence


def test_scoped_delta_not_vacuous_when_baseline_empty():
    # Nothing was red at baseline in scope -> never vacuous, byte-identical.
    proc = SimpleNamespace(returncode=0, stdout="1 passed in 0.01s", stderr="")
    ok, evidence = _scoped_delta_verdict(
        proc, ["tests/test_x.py"], _plan(), frozenset())
    assert ok is True
    assert "delta_vacuous" not in evidence


# --- ordering guard: delta_run_invalid still wins, never vacuous ---------------

def test_ordering_guard_invalid_run_never_stamps_vacuous(tmp_path, monkeypatch):
    # An AFTER run that collapses (usage error) must fail CLOSED via the
    # existing delta_run_invalid path — even though the baseline scope was
    # entirely red — and delta_vacuous must NEVER be stamped in that case.
    monkeypatch.setattr(
        av, "suite_after_failing",
        lambda root: (
            SimpleNamespace(commands=[["python", "-m", "pytest", "-q"]],
                            results=[{"command": ["python", "-m", "pytest", "-q"],
                                      "returncode": 5, "stdout": "", "stderr": "",
                                      "timed_out": False, "ok": False}],
                            ok=False, pytest_missing=False),
            frozenset()))
    out: dict = {}
    stood = av._verify_delta_green(
        tmp_path, out, frozenset({"tests/test_env.py::test_pre"}), None)
    assert stood is False
    assert out["verified"] is False
    assert out["delta_run_invalid"] is True
    assert "delta_vacuous" not in out


def test_scoped_ordering_guard_invalid_run_never_vacuous():
    proc = SimpleNamespace(returncode=4, stdout="", stderr="")
    ok, evidence = _scoped_delta_verdict(
        proc, ["tests/test_x.py"], _plan(),
        frozenset({"tests/test_x.py::test_pre"}))
    assert ok is False
    assert evidence["delta_run_invalid"] is True
    assert "delta_vacuous" not in evidence


# --- apply_rename(impact_scope=True): end-to-end vacuous labeling, not rolled back

def _all_red_impact_project(root: Path) -> None:
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "core.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(
        "from app.core import f\n\ndef test_f():\n    assert f() == 999\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")


def test_impact_scope_vacuous_delta_labeled_not_rolled_back(tmp_path):
    _all_red_impact_project(tmp_path)
    _available, baseline = suite_failing_nodes(tmp_path)
    assert baseline == frozenset({"tests/test_core.py::test_f"})

    before = (tmp_path / "app" / "core.py").read_text()
    plan = _edit_plan("app/core.py", before, "def f():\n    return 1  # tidy\n")
    res = apply_rename(tmp_path, plan, verify=True, impact_scope=True,
                       baseline_failing=baseline)

    assert res["applied"] is True
    assert res["rolled_back"] is False  # LABELING only, never blocked
    assert res["delta_vacuous"] is True
    assert res["verification_strength"]["level"] == DELTA_VACUOUS


# --- CompileStep / develop_session tier plumbing --------------------------------

def test_compile_step_vacuous_tier_is_baseline_red_but_coverage_verified_untouched():
    # ``coverage_verified`` is a SHARED verdict property that ``app/agent/
    # assist.py``'s ``_commit_result`` gates a real ``git commit`` on (a file
    # outside this fix's scope, exercised by no test here) — so it is
    # DELIBERATELY left unchanged by ``delta_vacuous``. The honest vacuous-delta
    # label lives ONLY in the label/render surfaces that check
    # ``delta_vacuous`` directly and take priority over this property:
    # ``ds._tier_for`` (below) and ``_compile_tier_tag``/``_compile_tier_counts``
    # (see the render tests further down).
    step = CompileStep(operator="modernize", target="app/core.py:f",
                       description="modernize x == None",
                       fitness_before=1.0, fitness_after=0.0,
                       verified=True, coverage="function", tier=1,
                       delta_vacuous=True)
    assert step.coverage_verified is True
    assert ds._tier_for(step) == ds.TIER_BASELINE_RED
    assert step.to_dict()["delta_vacuous"] is True


def test_compile_step_default_delta_vacuous_false_byte_identical():
    step = CompileStep(operator="modernize", target="app/core.py:f",
                       description="modernize x == None",
                       fitness_before=1.0, fitness_after=0.0,
                       verified=True, coverage="function", tier=1)
    assert step.coverage_verified is True
    assert "delta_vacuous" not in step.to_dict()
    assert ds._tier_for(step) == ds.TIER_VERIFIED


# --- render surfaces the label --------------------------------------------------

def test_compile_tier_tag_vacuous_move_reads_baseline_red():
    step = CompileStep(operator="modernize", target="app/core.py:f",
                       description="d", fitness_before=1.0, fitness_after=0.0,
                       verified=True, coverage="function", tier=1,
                       delta_vacuous=True)
    tag = _compile_tier_tag(step)
    assert "baseline-red" in tag
    assert "unverifiable" in tag
    assert "✅" not in tag


def test_render_compile_markdown_vacuous_move_line_has_no_checkmark():
    from app.engine.objective_compiler import CompileResult

    result = CompileResult(objective="modernize", fitness_start=1.0,
                           fitness_end=0.0, applied=True)
    result.steps.append(CompileStep(
        operator="modernize", target="app/core.py:f", description="modernize it",
        fitness_before=1.0, fitness_after=0.0, verified=True,
        coverage="function", tier=1, delta_vacuous=True))
    md = render_compile_markdown(result)
    assert "baseline-red" in md
    assert "unverifiable" in md
    line = next(ln for ln in md.splitlines() if "modernize it" in ln)
    assert "✅" not in line
    assert "1 baseline-red (unverifiable)" in md


def test_render_session_markdown_vacuous_move_labeled():
    move = SessionMove(objective="modernize", operator="modernize",
                       target="app/core.py:f", description="modernize it",
                       tier=ds.TIER_BASELINE_RED)
    obj = SessionObjective(objective="modernize", moves=[move])
    report = SessionReport(applied=True, objectives=[obj])
    md = ds.render_session_markdown(report)
    assert "baseline-red" in md
    assert "unverifiable" in md
    line = next(ln for ln in md.splitlines() if "modernize it" in ln)
    assert "✅" not in line
    assert report.baseline_red_moves == 1
    assert report.to_dict()["baseline_red_moves"] == 1


def test_session_report_no_baseline_red_moves_is_additive_absent():
    report = SessionReport(applied=True)
    assert report.baseline_red_moves == 0
    assert "baseline_red_moves" not in report.to_dict()


# --- boundary fix: coverage_verified stays a byte-identical shared verdict -----

def test_compile_tier_counts_vacuous_step_not_double_counted():
    # A vacuous step whose verified/coverage would otherwise satisfy
    # ``coverage_verifies`` must land in ``baseline_red``, NEVER also in
    # ``verified`` — ``coverage_verified`` itself no longer excludes
    # ``delta_vacuous`` (see the property's docstring), so this render-only
    # tally must apply the exclusion itself or double-count the step.
    result = CompileResult(objective="modernize", fitness_start=1.0,
                           fitness_end=0.0, applied=True)
    vacuous_step = CompileStep(
        operator="modernize", target="app/core.py:f", description="d",
        fitness_before=1.0, fitness_after=0.0, verified=True,
        coverage="function", tier=1, delta_vacuous=True)
    assert vacuous_step.coverage_verified is True  # the shared verdict, untouched
    result.steps.append(vacuous_step)
    result.steps.append(CompileStep(
        operator="modernize", target="app/core.py:g", description="d2",
        fitness_before=1.0, fitness_after=0.0, verified=True,
        coverage="function", tier=1))
    landed, verified, weak, baseline_red = _compile_tier_counts(result)
    assert landed == 2
    assert verified == 1       # only the genuinely-covered step
    assert baseline_red == 1   # the vacuous step, its own honest tier
    assert weak == 0
    assert verified + weak + baseline_red == landed  # no double count, no gap


# --- adversarial-review fix: last-match "N passed" parsing ---------------------

def test_passed_count_of_text_ignores_earlier_decoy_in_captured_output():
    # pytest prints a FAILED test's own captured stdout/stderr BEFORE the real
    # tail summary line. If that captured text itself contains an earlier
    # ``N passed``-shaped substring (e.g. a fixture string, as this very test
    # file's own fixtures do), a first-match search must not be fooled by it —
    # the true tail count (here genuinely 0) must win.
    text = (
        "----------------------------- Captured stdout call ------------------------------\n"
        "expected == '2 passed, 1 failed in 0.01s'\n"
        "FAILED tests/test_x.py::test_pre - boom\n"
        "0 passed, 1 failed in 0.01s"
    )
    assert passed_count_of_text(text) == 0


def test_scoped_delta_vacuous_not_defeated_by_decoy_passed_substring():
    proc = SimpleNamespace(
        returncode=1,
        stdout=("----------------------------- Captured stdout call ------------------------------\n"
                "expected == '2 passed, 1 failed in 0.01s'\n"
                "FAILED tests/test_x.py::test_pre - boom\n"
                "0 passed, 1 failed in 0.01s"),
        stderr="")
    ok, evidence = _scoped_delta_verdict(
        proc, ["tests/test_x.py"], _plan(),
        frozenset({"tests/test_x.py::test_pre"}))
    assert ok is True
    # RED without the last-match fix: the decoy "2 passed" would be read as the
    # tail count, ``delta_vacuous`` would evaluate False, and this baseline-red
    # move would silently keep a plain ``verified`` label.
    assert evidence["delta_vacuous"] is True


def test_verify_delta_green_vacuous_not_defeated_by_decoy_passed_substring(
        monkeypatch):
    # Same decoy scenario, but through the whole-suite ``_verify_delta_green``
    # path — and specifically through ``evidence["tests_passed"]``'s
    # first-match fragility (``proof_of_fix.summarize_test_run``), which the
    # fix bypasses via ``_robust_passed_count`` for the gating decision.
    decoy_text = (
        "----------------------------- Captured stdout call ------------------------------\n"
        "expected == '2 passed, 1 failed in 0.01s'\n"
        "FAILED tests/test_x.py::test_pre - boom\n"
        "0 passed, 1 failed in 0.01s")
    summary = SimpleNamespace(
        commands=[["python", "-m", "pytest", "-q"]],
        results=[{"command": ["python", "-m", "pytest", "-q"],
                  "returncode": 1, "stdout": decoy_text, "stderr": "",
                  "timed_out": False, "ok": False}],
        ok=False, pytest_missing=False)
    after_failing = frozenset({"tests/test_x.py::test_pre"})
    monkeypatch.setattr(av, "suite_after_failing",
                        lambda root: (summary, after_failing))
    out: dict = {}
    stood = av._verify_delta_green(
        Path("."), out, frozenset({"tests/test_x.py::test_pre"}), None)
    assert stood is True
    assert out["verified"] is True
    assert out["delta_vacuous"] is True
    assert out["verification_strength"]["level"] == DELTA_VACUOUS
