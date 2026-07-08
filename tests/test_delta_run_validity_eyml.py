"""Falsifiable tests for the delta-run VALIDITY guard — the fix for the
second fake-green class found by the 2026-07-08 trust-chain audit.

Every delta-green verdict diffs pytest ``FAILED``/``ERROR`` short-summary node
lines. Those lines only exist when pytest genuinely reached its per-test
summary (exit 0, or exit 1 with at least one node printed). A run that
COLLAPSED — a broken ``conftest.py`` under ``--continue-on-collection-errors``
exits 4 with ZERO node lines; nothing collected exits 5; a timeout truncates;
an interpreter without pytest exits 1 printing "No module named pytest" — used
to produce an EMPTY after-set that diffed against the baseline as "no
regressions": ``verified=True`` for a run that measured nothing. Empirically
demonstrated pre-fix; each behavioral test here failed on the pre-fix code.

Guarded sites (all four): ``_verify_delta_green`` (full-suite per-move),
``_scoped_delta_verdict`` (impact-scoped per-move), the bridge's
``_run_gate_suite`` (maintain / review --fix), and the end-of-session rollback
backstop (``_maybe_rollback_regression``).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.engine import develop_session as ds
from app.engine.idea_action_bridge import IdeaActionBridge
from app.execution import _apply_verify as av
from app.execution.cross_file_rename import RenamePlan, _scoped_delta_verdict

PYTEST_CMD = ["python", "-m", "pytest", "-q"]


def _res(rc: int, stdout: str = "", timed_out: bool = False,
         command: list | None = None) -> dict:
    return {"command": command or PYTEST_CMD, "returncode": rc,
            "stdout": stdout, "stderr": "", "timed_out": timed_out,
            "ok": rc == 0 and not timed_out}


def _summary(results: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(commands=[PYTEST_CMD], results=results,
                           ok=False, pytest_missing=False)


# --- delta_run_valid: the shared validity rule ---------------------------------

def test_collapsed_exit_codes_are_invalid():
    # 2 interrupted / 3 internal error / 4 usage error / 5 nothing collected:
    # pytest never reached a comparable per-test summary.
    for rc in (2, 3, 4, 5):
        assert av.delta_run_valid(_summary([_res(rc)]), frozenset()) is False


def test_timeout_is_invalid():
    assert av.delta_run_valid(
        _summary([_res(1, timed_out=True)]), frozenset({"t.py::x"})) is False


def test_exit_one_with_zero_nodes_is_invalid():
    # ``python -m pytest`` that never launched ("No module named pytest") also
    # exits 1 — with zero node lines. rc alone cannot distinguish it; the
    # zero-node rule does.
    assert av.delta_run_valid(_summary([_res(1)]), frozenset()) is False


def test_honest_runs_are_valid():
    assert av.delta_run_valid(_summary([_res(0)]), frozenset()) is True
    assert av.delta_run_valid(
        _summary([_res(1, stdout="FAILED t.py::x - boom")]),
        frozenset({"t.py::x"})) is True


def test_non_pytest_command_is_exempt_from_the_pytest_rc_rule():
    # A mixed repo's ``npm test`` legitimately exits 1 on a pre-existing JS red
    # without contributing pytest nodes — it must not invalidate the run.
    results = [_res(0), _res(1, command=["npm", "test", "--silent"])]
    assert av.delta_run_valid(_summary(results), frozenset()) is True


def test_empty_results_never_validate():
    assert av.delta_run_valid(_summary([]), frozenset()) is False


# --- _verify_delta_green: the full-suite per-move gate --------------------------

def _collapsed_after(monkeypatch, rc: int = 5):
    monkeypatch.setattr(
        av, "suite_after_failing",
        lambda root: (_summary([_res(rc)]), frozenset()))


def test_full_suite_delta_fails_closed_on_collapsed_run(tmp_path, monkeypatch):
    # Pre-fix: introduced = ∅ - baseline = ∅ → verified=True off a run that
    # measured NOTHING. Post-fix: unverified, change rolled back by the caller.
    _collapsed_after(monkeypatch)
    out: dict = {}
    stood = av._verify_delta_green(
        tmp_path, out, frozenset({"tests/test_env.py::test_pre"}), None)
    assert stood is False
    assert out["verified"] is False
    assert out["delta_run_invalid"] is True


# --- _scoped_delta_verdict: the impact-scoped per-move gate ---------------------

def _plan() -> RenamePlan:
    return RenamePlan(old="app/core.py", new="edit")


def test_scoped_delta_fails_closed_on_usage_error():
    proc = SimpleNamespace(returncode=4, stdout="", stderr="")
    ok, evidence = _scoped_delta_verdict(proc, ["tests/test_x.py"], _plan(),
                                         frozenset())
    assert ok is False
    assert evidence["passed"] is False
    assert evidence["delta_run_invalid"] is True


def test_scoped_delta_fails_closed_on_exit_one_without_nodes():
    proc = SimpleNamespace(returncode=1,
                           stdout="", stderr="No module named pytest")
    ok, evidence = _scoped_delta_verdict(proc, ["tests/test_x.py"], _plan(),
                                         frozenset())
    assert ok is False
    assert evidence["delta_run_invalid"] is True


def test_scoped_delta_still_tolerates_a_real_pre_existing_red():
    # rc 1 WITH the node line, and that node already red at baseline: the
    # honest delta-green landing must keep working.
    proc = SimpleNamespace(
        returncode=1, stdout="FAILED tests/test_x.py::test_pre - boom",
        stderr="")
    ok, evidence = _scoped_delta_verdict(
        proc, ["tests/test_x.py"], _plan(),
        frozenset({"tests/test_x.py::test_pre"}))
    assert ok is True
    assert evidence["delta_green"]["introduced"] == []


# --- the bridge gate (maintain / review --fix) ----------------------------------

def test_bridge_delta_gate_fails_closed_on_collapsed_run(tmp_path, monkeypatch):
    _collapsed_after(monkeypatch)
    out: dict = {}
    _summary_obj, suite_ok = IdeaActionBridge._run_gate_suite(
        str(tmp_path), out, frozenset({"tests/test_env.py::test_pre"}))
    assert suite_ok is False
    assert out["delta_run_invalid"] is True


# --- the end-of-session rollback backstop ---------------------------------------

def test_backstop_fails_closed_and_restores_on_invalid_rerun(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    before = {"a.py": "x = 1\n"}
    after = {"a.py": "x = 2\n"}
    report = ds.SessionReport(applied=True)
    monkeypatch.setattr(ds, "_failing_nodes_checked",
                        lambda root: (False, frozenset()))
    effective = ds._maybe_rollback_regression(
        report, tmp_path, before, after, frozenset({"t.py::pre"}))
    assert effective == before
    assert report.backstop_run_invalid is True
    assert report.regression_rolled_back is True
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_backstop_valid_clean_rerun_keeps_the_session(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    before = {"a.py": "x = 1\n"}
    after = {"a.py": "x = 2\n"}
    report = ds.SessionReport(applied=True)
    monkeypatch.setattr(ds, "_failing_nodes_checked",
                        lambda root: (True, frozenset({"t.py::pre"})))
    effective = ds._maybe_rollback_regression(
        report, tmp_path, before, after, frozenset({"t.py::pre"}))
    assert effective == after
    assert report.backstop_run_invalid is False
    assert report.regression_rolled_back is False
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\n"
