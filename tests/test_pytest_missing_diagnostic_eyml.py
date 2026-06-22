"""VERIFICATION-UNAVAILABLE — pytest missing is a DISTINCT, loud, honest tier.

The empirically-confirmed bug: when ``<python> -m pytest`` runs under an
interpreter that has no pytest, the subprocess exits non-zero with an EMPTY
stdout and a stderr line ``<path>: No module named pytest``. ``CommandResult.ok``
is False, so the run was misread as a RED suite — the develop/ideate loops then
read the baseline as red, force blind impact-scoping (whose probes ALSO can't
import pytest), and roll EVERY landing back, reporting ``0 executable``: a silent,
total under-delivery with no actionable signal.

This pins the fix end to end:

  * ``TestRunSummary`` carries ``pytest_missing`` / ``pytest_interpreter`` — set by
    a proactive ``-c "import pytest"`` probe OR the defensive stderr signature.
  * a NEW tier ``verification-unavailable`` (a SIBLING of ``no-suite``, NOT folded
    into it nor into a real failure) is stamped, and the change is NOT rolled back
    as failed — proof-carrying: can't verify => don't touch, never fake-green.
  * the LOUD, actionable message naming the interpreter reaches EVERY entry point:
    the develop session (markdown + --json) and the ideate/maintain apply summary.
  * a genuinely-RED suite STILL reads red, and a no-suite project is UNCHANGED —
    the new branch fires ONLY on the pytest-missing signature.

Deterministic, stdlib + pytest only — the runner/probe are monkeypatched so no
real subprocess (and so no real network/clock) is involved.
"""

from __future__ import annotations

from pathlib import Path

import app.skills.execution.run_tests as run_tests_mod
from app.execution._apply_verify import (
    NO_SUITE,
    VERIFICATION_UNAVAILABLE,
    mark_verification_unavailable,
    run_full_suite_verification,
    verification_unavailable_interpreter,
)
from app.skills.execution.run_tests import RunTestsSkill

_INTERP = "/usr/local/bin/python"
_MISSING_STDERR = f"{_INTERP}: No module named pytest"


# --- helpers -----------------------------------------------------------------

def _clear_probe_cache(monkeypatch) -> None:
    """Isolate the memoized ``pytest_importable`` cache per test."""
    monkeypatch.setattr(run_tests_mod, "_PYTEST_IMPORTABLE", {})


class _FakeResult:
    """A CommandRunner result double (only the fields the runner reads)."""

    def __init__(self, ok: bool, stderr: str = "", stdout: str = "") -> None:
        self.ok = ok
        self.returncode = 0 if ok else 1
        self.stderr = stderr
        self.stdout = stdout
        self.command: list[str] = []
        self.cwd = "/tmp"
        self.duration_seconds = 0.0
        self.timed_out = False


def _patch_probe(monkeypatch, *, importable: bool) -> None:
    """Make the proactive ``import pytest`` probe deterministic (no subprocess)."""
    _clear_probe_cache(monkeypatch)
    monkeypatch.setattr(
        run_tests_mod, "pytest_importable",
        lambda python: importable)


# --- TestRunSummary fields default falsy (the shared-double lock) -------------

def test_summary_fields_default_falsy():
    # The ``_Summary`` doubles in test_apply_verify_shared.py carry only
    # ok/commands; the NEW fields MUST default falsy so a summary for a project
    # WITH pytest is byte-identical and those locks pass unchanged.
    s = run_tests_mod.TestRunSummary(project_root="/tmp")
    assert s.pytest_missing is False
    assert s.pytest_interpreter == ""


# --- detection: proactive probe sets the fields ------------------------------

def test_run_flags_pytest_missing_via_proactive_probe(tmp_path, monkeypatch):
    # A detectable pytest suite + a probe that says pytest is NOT importable ->
    # the summary is flagged WITHOUT even running the (doomed) pytest command.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")

    _patch_probe(monkeypatch, importable=False)

    # The interpreter the runner would invoke is what _detect_commands chose.
    cmds = RunTestsSkill()._detect_commands(tmp_path)
    interp = cmds[0][0]

    summary = RunTestsSkill().run(tmp_path)
    assert summary.pytest_missing is True
    assert summary.pytest_interpreter == interp


def test_run_no_flag_when_pytest_importable(tmp_path, monkeypatch):
    # The common path: pytest IS importable -> the fields stay falsy (the run
    # proceeds exactly as before).
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")

    _patch_probe(monkeypatch, importable=True)
    # Don't actually spawn pytest: stub the runner's per-command run to a pass.
    monkeypatch.setattr(
        RunTestsSkill, "_result_to_dict",
        lambda self, r: {"ok": True, "stdout": "1 passed", "stderr": "",
                         "returncode": 0})
    monkeypatch.setattr(
        run_tests_mod.CommandRunner, "run",
        lambda self, spec: _FakeResult(ok=True, stdout="1 passed"))

    summary = RunTestsSkill().run(tmp_path)
    assert summary.pytest_missing is False
    assert summary.pytest_interpreter == ""


# --- detection: the stderr signature backstop --------------------------------

def test_run_flags_pytest_missing_via_stderr_backstop(tmp_path, monkeypatch):
    # The DEFENSIVE backstop: even when the proactive probe is bypassed (here the
    # probe says "importable" but the actual run fails with the missing-pytest
    # signature), a failed pytest run carrying ``No module named pytest`` still
    # flags the state and names the interpreter — never read as a real RED suite.
    _clear_probe_cache(monkeypatch)
    monkeypatch.setattr(run_tests_mod, "pytest_importable", lambda python: True)
    monkeypatch.setattr(
        run_tests_mod.CommandRunner, "run",
        lambda self, spec: _FakeResult(ok=False, stderr=_MISSING_STDERR))

    cmd = [_INTERP, "-m", "pytest", "-q"]
    summary = RunTestsSkill().run(tmp_path, commands=[cmd])
    assert summary.pytest_missing is True
    assert summary.pytest_interpreter == _INTERP
    # ...and the overall run is NOT ok (the command did fail) — the DISTINCTION is
    # carried by ``pytest_missing``, not by pretending the run passed.
    assert summary.ok is False


def test_stderr_backstop_quoted_module_name(tmp_path, monkeypatch):
    # Some Python versions quote the module: ``No module named 'pytest'``.
    _clear_probe_cache(monkeypatch)
    monkeypatch.setattr(run_tests_mod, "pytest_importable", lambda python: True)
    monkeypatch.setattr(
        run_tests_mod.CommandRunner, "run",
        lambda self, spec: _FakeResult(
            ok=False, stderr=f"{_INTERP}: No module named 'pytest'"))

    summary = RunTestsSkill().run(
        tmp_path, commands=[[_INTERP, "-m", "pytest", "-q"]])
    assert summary.pytest_missing is True


def test_real_red_suite_is_not_flagged_missing(tmp_path, monkeypatch):
    # A GENUINELY red suite (a real FAILED line, NOT the missing-pytest signature)
    # must STILL read red and must NOT be flagged pytest_missing — the branch fires
    # only on the missing signature.
    _clear_probe_cache(monkeypatch)
    monkeypatch.setattr(run_tests_mod, "pytest_importable", lambda python: True)
    monkeypatch.setattr(
        run_tests_mod.CommandRunner, "run",
        lambda self, spec: _FakeResult(
            ok=False,
            stdout="FAILED tests/test_x.py::test_x - AssertionError\n1 failed\n"))

    summary = RunTestsSkill().run(
        tmp_path, commands=[[_INTERP, "-m", "pytest", "-q"]])
    assert summary.ok is False
    assert summary.pytest_missing is False
    assert summary.pytest_interpreter == ""


# --- pytest_importable: memoized, conservative on launch failure --------------

def test_pytest_importable_memoized(monkeypatch):
    _clear_probe_cache(monkeypatch)
    calls = {"n": 0}

    def _run(self, spec):
        calls["n"] += 1
        return _FakeResult(ok=True)

    monkeypatch.setattr(run_tests_mod.CommandRunner, "run", _run)
    first = run_tests_mod.pytest_importable(_INTERP)
    second = run_tests_mod.pytest_importable(_INTERP)
    assert first is True and second is True
    assert calls["n"] == 1  # the second call read the cache, did not re-probe


def test_pytest_importable_false_when_launch_raises(monkeypatch):
    _clear_probe_cache(monkeypatch)

    def _boom(self, spec):
        raise OSError("cannot spawn")

    monkeypatch.setattr(run_tests_mod.CommandRunner, "run", _boom)
    # A probe that can't even launch is conservatively "not importable" (we must
    # not claim a run could verify when we cannot prove pytest is present).
    assert run_tests_mod.pytest_importable(_INTERP) is False


# --- the verdict layer: NOT rolled back, DISTINCT tier ------------------------

class _Summary:
    """A TestRunSummary double for run_full_suite_verification."""

    def __init__(self, *, ok, commands, pytest_missing=False,
                 pytest_interpreter="", results=None) -> None:
        self.ok = ok
        self.commands = commands
        self.pytest_missing = pytest_missing
        self.pytest_interpreter = pytest_interpreter
        self.results = results or []


def _patch_verify_runner(monkeypatch, summary: _Summary) -> None:
    import app.engine.proof_of_fix as proof_mod

    class _FakeSkill:
        def run(self, root):  # noqa: ANN001 - test double
            return summary

    monkeypatch.setattr(run_tests_mod, "RunTestsSkill", _FakeSkill)
    monkeypatch.setattr(
        proof_mod, "summarize_test_run",
        lambda s: {"ok": getattr(s, "ok", False)})


def test_full_suite_verification_pytest_missing_not_rolled_back(monkeypatch):
    # pytest missing -> the change STANDS (returns True), is NOT verified, is NOT
    # rolled back, and carries the DISTINCT verification-unavailable tier naming
    # the interpreter — never the RED verdict that would roll it back.
    _patch_verify_runner(monkeypatch, _Summary(
        ok=False, commands=[[_INTERP, "-m", "pytest", "-q"]],
        pytest_missing=True, pytest_interpreter=_INTERP))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)

    assert stands is True                      # NOT treated as a failure
    assert out["rolled_back"] is False         # nothing rolled back as failed
    assert out["verified"] is False            # honestly unverified
    assert out["suite_available"] is False
    assert out["verification_unavailable"] is True
    assert out["pytest_interpreter"] == _INTERP
    level = out["verification_strength"]["level"]
    assert level == VERIFICATION_UNAVAILABLE
    # DISTINCT from no-suite and from a real failure.
    assert level != NO_SUITE
    assert level != "baseline-red"


def test_full_suite_verification_real_failure_unchanged(monkeypatch):
    # A genuinely RED suite (not pytest-missing) STILL requests rollback exactly
    # as before — the new branch never touches it.
    _patch_verify_runner(monkeypatch, _Summary(
        ok=False, commands=[["pytest"]], pytest_missing=False))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is False                     # the caller will roll back
    assert out["verified"] is False
    assert "rolled_back" not in out            # caller's job, as before
    assert "verification_unavailable" not in out


def test_full_suite_verification_no_suite_unchanged(monkeypatch):
    # No commands -> the no-suite path is byte-identical: stands, no rollback,
    # the no-suite tier (NOT verification-unavailable).
    _patch_verify_runner(monkeypatch, _Summary(
        ok=False, commands=[], pytest_missing=False))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is True
    assert out["rolled_back"] is False
    assert out["suite_available"] is False
    assert out["verification_strength"]["level"] == NO_SUITE
    assert "verification_unavailable" not in out


def test_full_suite_verification_green_unchanged(monkeypatch):
    # The happy path is untouched: green suite -> verified True, not rolled back.
    _patch_verify_runner(monkeypatch, _Summary(ok=True, commands=[["pytest"]]))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is True
    assert out["verified"] is True
    assert out["rolled_back"] is False
    assert "verification_unavailable" not in out


# --- mark_verification_unavailable: the additive stamp ------------------------

def test_mark_verification_unavailable_stamp():
    out: dict = {}
    mark_verification_unavailable(out, _INTERP)
    assert out["suite_available"] is False
    assert out["verification_unavailable"] is True
    assert out["pytest_interpreter"] == _INTERP
    assert out["verification_strength"]["level"] == VERIFICATION_UNAVAILABLE
    assert out["verification_strength"]["suite_available"] is False


# --- the shared entry guard ---------------------------------------------------

def test_entry_guard_returns_interpreter_when_missing(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    _patch_probe(monkeypatch, importable=False)

    interp = verification_unavailable_interpreter(tmp_path)
    assert interp is not None
    # It is the interpreter _detect_commands would invoke.
    assert interp == RunTestsSkill()._detect_commands(tmp_path)[0][0]


def test_entry_guard_none_when_importable(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    _patch_probe(monkeypatch, importable=True)
    assert verification_unavailable_interpreter(tmp_path) is None


def test_entry_guard_none_for_suiteless_project(tmp_path, monkeypatch):
    # A non-pytest / suite-less project is NOT verification-unavailable — it has
    # the honest no-suite story, so the guard returns None (the probe is never
    # even consulted because no pytest command is detected).
    (tmp_path / "README.md").write_text("# project\n")
    _patch_probe(monkeypatch, importable=False)
    assert verification_unavailable_interpreter(tmp_path) is None


# --- develop session: short-circuit + loud message in markdown AND --json -----

def _patch_session_unavailable(monkeypatch) -> None:
    """Force the develop session's entry guard to report unavailable."""
    import app.engine.develop_session as ds

    monkeypatch.setattr(ds, "_verification_unavailable", lambda root: _INTERP)


def test_session_short_circuits_and_lands_nothing(tmp_path, monkeypatch):
    from app.engine.develop_session import run_develop_session

    _patch_session_unavailable(monkeypatch)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    assert report.pytest_missing is True
    assert report.pytest_interpreter == _INTERP
    # Declined up front: nothing landed, nothing rolled back as failed.
    assert report.total_moves == 0
    assert report.objectives == []
    assert report.regression_rolled_back is False


def test_session_no_verify_is_unaffected(tmp_path, monkeypatch):
    # --no-verify already declares its moves UNVERIFIED by the user's choice, so
    # the guard does NOT fire there (it would change that path's behaviour). The
    # guard helper must not even be consulted; assert the flag stays falsy.
    import app.engine.develop_session as ds
    from app.engine.develop_session import run_develop_session

    def _boom(root):
        raise AssertionError("guard consulted under --no-verify")

    monkeypatch.setattr(ds, "_verification_unavailable", _boom)
    report = run_develop_session(str(tmp_path), apply=False, verify=False)
    assert report.pytest_missing is False


def test_session_markdown_carries_loud_message(monkeypatch):
    from app.engine.develop_session import (
        SessionReport,
        render_session_markdown,
    )

    report = SessionReport(applied=True)
    report.pytest_missing = True
    report.pytest_interpreter = _INTERP
    md = render_session_markdown(report)

    assert "verification is unavailable" in md.lower()
    assert "pytest is not importable" in md
    assert _INTERP in md
    assert "pip install pytest" in md
    assert ".venv" in md
    assert "rolled back as failed" in md
    # The misleading verification stats block is NOT rendered (nothing ran).
    assert "verified** (a test exercises" not in md


def test_session_to_dict_carries_loud_message():
    from app.engine.develop_session import SessionReport

    report = SessionReport(applied=True)
    report.pytest_missing = True
    report.pytest_interpreter = _INTERP
    data = report.to_dict()

    assert data["pytest_missing"] is True
    assert data["pytest_interpreter"] == _INTERP
    assert _INTERP in data["verification_unavailable"]
    assert "pytest is not importable" in data["verification_unavailable"]


def test_session_to_dict_clean_report_has_no_message():
    # A normal report (pytest present) is byte-identical: no message key.
    from app.engine.develop_session import SessionReport

    data = SessionReport(applied=True).to_dict()
    assert data["pytest_missing"] is False
    assert "verification_unavailable" not in data


# --- the bridge apply summary (ideate --apply / maintain) ---------------------

def _patch_bridge_unavailable(monkeypatch) -> None:
    """Force the shared entry guard the bridge consults to report unavailable."""
    import app.execution._apply_verify as av

    monkeypatch.setattr(
        av, "verification_unavailable_interpreter", lambda root: _INTERP)


def test_bridge_apply_plan_declines(tmp_path, monkeypatch):
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan

    _patch_bridge_unavailable(monkeypatch)
    summary = IdeaActionBridge().apply_plan(
        ActionPlan(steps=[], mode="supervised"), str(tmp_path),
        mode="supervised", verify=True)

    assert summary["applied"] == 0
    assert summary["rolled_back"] == 0
    assert summary["blocked"] == 0
    assert summary["results"] == []
    assert _INTERP in summary["verification_unavailable"]
    assert "pytest is not importable" in summary["verification_unavailable"]
    assert summary["pytest_interpreter"] == _INTERP


def test_bridge_apply_plan_no_verify_unaffected(tmp_path, monkeypatch):
    # --no-verify must NOT consult the guard (byte-identical to today).
    import app.execution._apply_verify as av
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan

    def _boom(root):
        raise AssertionError("guard consulted under --no-verify")

    monkeypatch.setattr(av, "verification_unavailable_interpreter", _boom)
    summary = IdeaActionBridge().apply_plan(
        ActionPlan(steps=[], mode="supervised"), str(tmp_path),
        mode="supervised", verify=False)
    assert "verification_unavailable" not in summary


def test_maintain_markdown_surfaces_the_message(tmp_path, monkeypatch):
    from app.engine.idea_action_bridge import (
        IdeaActionBridge,
        render_maintenance_markdown,
    )
    from app.models.idea import ActionPlan

    _patch_bridge_unavailable(monkeypatch)
    summary = IdeaActionBridge().apply_plan(
        ActionPlan(steps=[], mode="supervised"), str(tmp_path),
        mode="supervised", verify=True)
    md = render_maintenance_markdown(summary, str(tmp_path))

    assert "pytest is not importable" in md
    assert _INTERP in md
    assert "pip install pytest" in md
    # The misleading "Applied: 0 ... executable steps" line is NOT rendered.
    assert "executable steps" not in md


def test_ideate_apply_results_surfaces_the_message(tmp_path, monkeypatch, capsys):
    from app.cli_ideate import _print_apply_results
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import ActionPlan

    _patch_bridge_unavailable(monkeypatch)
    summary = IdeaActionBridge().apply_plan(
        ActionPlan(steps=[], mode="supervised"), str(tmp_path),
        mode="supervised", verify=True)
    _print_apply_results(summary)

    out = capsys.readouterr().out
    assert "pytest is not importable" in out
    assert _INTERP in out
    # NOT the misleading "applied 0 · rolled back 0" counts line (the message
    # itself legitimately contains "rolled back as failed", so target the count).
    assert "applied 0" not in out
    assert "executable steps" not in out


def test_maintain_markdown_normal_summary_unchanged(tmp_path):
    # A normal apply summary (no verification_unavailable key) renders the usual
    # report exactly as before — the new branch is additive/opt-in.
    from app.engine.idea_action_bridge import render_maintenance_markdown

    summary = {"mode": "supervised", "verify": True, "commit": False,
               "total_executable": 0, "applied": 0, "rolled_back": 0,
               "blocked": 0, "committed": 0, "results": []}
    md = render_maintenance_markdown(summary, str(tmp_path))
    assert "executable steps" in md            # the normal counts line is present
    assert "pytest is not importable" not in md
