"""FIX: standalone applied campaigns get the end-of-campaign regression backstop.

The 2026-07-08 adversarial audit finding: the transitive-regression full-suite
backstop existed ONLY in ``run_develop_session``. A standalone applied campaign —
``compile_objective(..., apply=True, verify=True)`` called directly (``apex
develop --objective X --apply``, the ``--auto`` sweep) or ``run_moves`` — ended
with NO re-verification, so a move whose impact-scoped per-move gate missed a
TRANSITIVELY-reachable previously-GREEN test landed and nothing ever re-checked.

The fix: when (and only when) the campaign OWNS its gate (``apply and verify``
and no caller-supplied ``baseline_failing`` — the develop session supplies one
and runs its OWN backstop), capture the before-snapshot + baseline failing-node
set up front; after the campaign, if files changed, re-run the suite ONCE, diff
failing nodes at TEST-FUNCTION granularity (``regressed_functions`` — a
pre-existing red is tolerated, never charged), and restore ALL changed files on
a regression. A COLLAPSED re-run (``suite_failing_nodes_checked`` invalid) fails
CLOSED: restore + honest disclosure, never "no regressions". The verdict is
disclosed on ``CompileResult.regression_backstop``.

Red-first: ``test_standalone_transitive_regression_rolled_back`` and
``test_run_moves_transitive_regression_rolled_back`` FAIL on the pre-fix code
(the regression landed and stayed — the exact hole
``test_transitive_regression_actually_lands_without_the_backstop`` used to pin
as the session-level violation witness). The additive-field pins cannot be
red-first (the field is new); they pin the contract end-to-end.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.objective_compiler import (
    BACKSTOP_CLEAN,
    BACKSTOP_INVALID,
    BACKSTOP_REGRESSED,
    CompileResult,
    Move,
    compile_objective,
    render_compile_markdown,
    run_moves,
)
from app.execution.cross_file_rename import RenamePlan

_WRAPPER_NODE = "tests/test_wrapper.py::test_missing_is_blank"


def _transitive_regression_project(root: Path) -> Path:
    """The proven transitive-regression shape (mirrors the develop-session
    fixture): a RED baseline forces impact-scoped thinking, ``modernize``'s
    ``== None`` -> ``is None`` rewrite passes its OWN in-scope test, and the
    previously-GREEN ``test_wrapper`` — reachable only through an exec-string
    dynamic import the scope scan cannot see — breaks."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("__all__ = []\n", encoding="utf-8")
    (root / "pkg" / "sentinel.py").write_text(
        "class Missing:\n"
        "    def __eq__(self, other):\n"
        "        return other is None or isinstance(other, Missing)\n"
        "    def __hash__(self):\n        return 0\n\n\n"
        "MISSING = Missing()\n", encoding="utf-8")
    (root / "pkg" / "check.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")
    (root / "pkg" / "wrapper.py").write_text(
        "from pkg.check import is_blank\n\n\n"
        "def blank_via_wrapper(value):\n    return is_blank(value)\n",
        encoding="utf-8")
    (root / "tests" / "test_check.py").write_text(
        "from pkg.check import is_blank\n"
        "def test_blank_none():\n    assert is_blank(None) is True\n"
        "def test_blank_value():\n    assert is_blank(7) is False\n",
        encoding="utf-8")
    (root / "tests" / "test_wrapper.py").write_text(
        "from pkg.sentinel import MISSING\n"
        "def _wrapper():\n"
        "    ns = {}\n"
        "    exec('from pkg.wrapper import blank_via_wrapper', ns)\n"
        "    return ns['blank_via_wrapper']\n"
        "def test_missing_is_blank():\n"
        "    assert _wrapper()(MISSING) is True\n", encoding="utf-8")
    (root / "tests" / "test_unrelated_red.py").write_text(
        "def test_preexisting_failure():\n    assert 1 == 2\n", encoding="utf-8")
    return root


def _dead_param_project(root: Path) -> Path:
    """A green-baseline project with one droppable (harmless) dead parameter."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "m.py").write_text(
        "__all__ = ['use']\n\n\n"
        "def render(text, color=None, width=80):\n"
        "    return text[:width]\n\n\n"
        "def use():\n"
        "    return render('hi', width=10)\n", encoding="utf-8")
    (root / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return root


# --- THE fix, end-to-end: compile_objective ------------------------------------

def test_standalone_transitive_regression_rolled_back(tmp_path: Path):
    # RED-FIRST: pre-fix this exact campaign LANDED the behaviour-changing move
    # (its own in-scope test passes) and the previously-GREEN transitive test
    # stayed broken forever — nothing ever re-checked.
    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text()

    result = compile_objective(str(tmp_path), objective="modernize",
                               apply=True, verify=True, scope_verify=True)

    # The backstop caught the transitive regression and restored EVERY file.
    assert result.regression_backstop == BACKSTOP_REGRESSED
    assert result.backstop_regressed_nodes == [_WRAPPER_NODE]
    assert result.steps == []  # nothing stands — no phantom contributions
    assert result.fitness_end == result.fitness_start
    assert (tmp_path / "pkg" / "check.py").read_text() == check_before
    assert "== None" in (tmp_path / "pkg" / "check.py").read_text()

    # Honest disclosure: rendered loudly, and on the dict artifact.
    md = render_compile_markdown(result)
    assert "backstop" in md
    assert "ROLLED BACK" in md or "restored" in md
    assert _WRAPPER_NODE in md
    d = result.to_dict()
    assert d["regression_backstop"] == BACKSTOP_REGRESSED
    assert d["backstop_regressed_nodes"] == [_WRAPPER_NODE]


def test_backstop_rollback_is_deterministic(tmp_path: Path):
    # Same fixture twice -> identical verdict, nodes, and report bytes.
    a = _transitive_regression_project(tmp_path / "a")
    b = _transitive_regression_project(tmp_path / "b")
    ra = compile_objective(str(a), objective="modernize", apply=True,
                           verify=True, scope_verify=True)
    rb = compile_objective(str(b), objective="modernize", apply=True,
                           verify=True, scope_verify=True)
    assert ra.regression_backstop == rb.regression_backstop == BACKSTOP_REGRESSED
    assert ra.backstop_regressed_nodes == rb.backstop_regressed_nodes
    assert render_compile_markdown(ra) == render_compile_markdown(rb)
    assert (a / "pkg" / "check.py").read_text() == (
        b / "pkg" / "check.py").read_text()


def test_clean_apply_keeps_changes_and_discloses_clean(tmp_path: Path):
    # NO-OVER-ROLLBACK: a green-baseline campaign whose changes break nothing
    # keeps its moves; the backstop verdict is the honest "clean".
    _dead_param_project(tmp_path)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert result.steps  # the move stands
    assert "color" not in (tmp_path / "app" / "m.py").read_text()
    assert result.regression_backstop == BACKSTOP_CLEAN
    assert result.backstop_regressed_nodes == []
    # Disclosed on the dict; the markdown carries NO rollback banner.
    assert result.to_dict()["regression_backstop"] == BACKSTOP_CLEAN
    assert "restored to its pre-campaign bytes" not in render_compile_markdown(result)


def test_pre_existing_red_is_tolerated_never_charged(tmp_path: Path):
    # RED BASELINE TOLERANCE: a pre-existing failing test (red at baseline and
    # still red after) never triggers the backstop rollback — the diff is at
    # test-function granularity against the captured baseline set.
    _dead_param_project(tmp_path)
    (tmp_path / "tests" / "test_red.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8")
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert result.steps  # the harmless move still lands
    assert "color" not in (tmp_path / "app" / "m.py").read_text()
    assert result.regression_backstop == BACKSTOP_CLEAN
    assert result.backstop_regressed_nodes == []


def test_backstop_fails_closed_on_collapsed_rerun(tmp_path: Path, monkeypatch):
    # FAIL-CLOSED: a re-run that collapsed before its per-test summary measured
    # NOTHING — reading it as "no regressions" would be the exact fake green the
    # backstop exists to prevent. The campaign is restored and the collapse
    # disclosed. (Baseline capture is the first checked call; the re-run the
    # second — the fake collapses only the re-run.)
    from app.execution import _apply_verify as av

    _dead_param_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    calls = {"n": 0}

    def fake_checked(root):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, True, frozenset()  # baseline: available, valid, green
        return True, False, frozenset()     # re-run: collapsed — NOT comparable

    monkeypatch.setattr(av, "suite_failing_nodes_checked", fake_checked)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert calls["n"] >= 2  # the re-run genuinely happened
    assert result.regression_backstop == BACKSTOP_INVALID
    assert result.steps == []
    assert (tmp_path / "app" / "m.py").read_text() == before  # restored
    md = render_compile_markdown(result)
    assert "could not vouch" in md or "fail closed" in md
    assert result.regression_backstop != BACKSTOP_CLEAN


# --- run_moves gets the same backstop -------------------------------------------

def _modernize_check_move(root: Path) -> Move:
    """A ready-built move that lands the behaviour-changing rewrite directly —
    the ``run_moves`` shape of the same transitive hole."""
    rel = "pkg/check.py"

    def _plan() -> RenamePlan:
        src = (root / rel).read_text(encoding="utf-8")
        plan = RenamePlan(old=rel, new="modernize None comparisons")
        plan.originals[rel] = src
        plan.new_contents[rel] = src.replace("value == None", "value is None")
        plan.edits_by_file[rel] = 1
        return plan

    return Move(operator="modernize", target=f"{rel}:modernize",
                description="modernize None comparisons in pkg/check.py",
                build_plan=_plan)


def test_run_moves_transitive_regression_rolled_back(tmp_path: Path):
    # RED-FIRST: pre-fix ``run_moves(apply=True)`` ended with no re-verification
    # at all — the impact-scoped gate let the move land and the broken
    # previously-GREEN transitive test was silently kept.
    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text()

    result = run_moves(str(tmp_path), [_modernize_check_move(tmp_path)],
                       label="multifile-landing", apply=True, verify=True,
                       scope_verify=True)

    assert result.regression_backstop == BACKSTOP_REGRESSED
    assert result.backstop_regressed_nodes == [_WRAPPER_NODE]
    assert result.steps == []
    assert (tmp_path / "pkg" / "check.py").read_text() == check_before


def test_run_moves_suiteless_project_backstop_not_armed(tmp_path: Path):
    # Empty edge: with NO detectable suite there is no baseline to diff — the
    # backstop stays un-armed ("" verdict, additive key absent) and the honest
    # no-suite tier carries the disclosure, exactly as before.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "check.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")
    result = run_moves(str(tmp_path), [_modernize_check_move(tmp_path)],
                       label="x", apply=True, verify=True)
    assert result.steps  # landed (no-suite tier), not rolled back
    assert result.regression_backstop == ""
    assert "regression_backstop" not in result.to_dict()


# --- the backstop must NOT double up or fire off the gated path ------------------

def test_dry_run_and_no_verify_never_arm_backstop(tmp_path: Path, monkeypatch):
    # A dry run gates nothing and a --no-verify apply is unverified by choice:
    # neither may pay a probe/snapshot. The arm helper exploding proves it is
    # never consulted.
    from app.engine import objective_compiler as oc

    _dead_param_project(tmp_path)

    def _boom(root):
        raise AssertionError("backstop armed off the gated-apply path")

    monkeypatch.setattr(oc, "_arm_backstop", _boom)
    dry = compile_objective(str(tmp_path), objective="dead-params", apply=False)
    assert dry.steps and dry.regression_backstop == ""
    unverified = compile_objective(str(tmp_path), objective="dead-params",
                                   apply=True, verify=False)
    assert unverified.steps and unverified.regression_backstop == ""
    assert "regression_backstop" not in unverified.to_dict()


def test_caller_supplied_baseline_skips_standalone_backstop(tmp_path: Path,
                                                            monkeypatch):
    # The develop session supplies ``baseline_failing`` and runs its OWN
    # end-of-session backstop — the standalone one must stand down (no double
    # suite runs, no double rollback authority).
    from app.engine import objective_compiler as oc

    _dead_param_project(tmp_path)

    def _boom(root):
        raise AssertionError("standalone backstop armed under a session baseline")

    monkeypatch.setattr(oc, "_arm_backstop", _boom)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True,
                               baseline_failing=frozenset())
    assert result.steps  # the campaign itself is unaffected
    assert result.regression_backstop == ""


# --- additive-field contract (cannot be red-first: the field is new) ------------

def test_backstop_field_default_keeps_existing_constructions_valid():
    r = CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0)
    assert r.regression_backstop == ""
    assert r.backstop_regressed_nodes == []
    d = r.to_dict()
    assert "regression_backstop" not in d
    assert "backstop_regressed_nodes" not in d
