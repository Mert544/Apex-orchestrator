"""VERIFICATION-UNAVAILABLE — ``compile_objective`` declines up front, honestly.

``compile_objective`` is the engine every single-objective ``apex develop`` mode
bottoms out in (``--objective`` directly; ``--all`` via ``compile_all``; ``--goal``
via ``fractal_develop.compile_goal``). Its sibling engines — the develop *session*
(``develop_session.run_develop_session``) and the maintain/ideate bridge
(``idea_action_bridge.apply_plan``) — already DECLINE up front when the target's own
interpreter (its ``.venv/bin/python``, which ``RunTestsSkill._python_for`` prefers)
cannot import pytest: they label the outcome "verification-unavailable" and land
NOTHING (proof-carrying — can't verify => don't touch).

The bug this pins: ``compile_objective`` had NO such guard, so on a genuinely-suited
external project whose interpreter can't import pytest it LANDED an unverified move
and mislabelled it "no-suite — applied, nothing verified it" — conflating "pytest is
missing" with "this project has no tests" and faking-green a move nothing verified.

This pins the fix:

  * a ``verify``-gated up-front guard (a straight PORT of the two siblings): when the
    project HAS a pytest suite but pytest is not importable, ``compile_objective``
    returns immediately with the loud ``verification_unavailable`` message + the
    offending ``pytest_interpreter`` and ZERO steps — NOTHING landed;
  * defence-in-depth: a ``CompileStep.verification_unavailable`` flag + a DISTINCT
    ``verification-unavailable`` tier tag, never folded into ``no-suite``;
  * a project where pytest IS importable is byte-identical (the guard returns None);
  * a genuinely suite-less project still reads ``no-suite`` — the distinction holds;
  * ``--no-verify`` is untouched (the guard is gated on ``verify``).

Deterministic, stdlib + pytest only — the ``import pytest`` probe is monkeypatched so
no real subprocess (and so no real network/clock) is involved. Fixture style mirrors
``tests/test_pytest_missing_diagnostic_eyml.py`` and ``tests/test_objective_compiler.py``.
"""

from __future__ import annotations

from pathlib import Path

import app.skills.execution.run_tests as run_tests_mod
from app.engine.objective_compiler import (
    CompileResult,
    CompileStep,
    compile_all,
    compile_objective,
    render_compile_markdown,
)
from app.skills.execution.run_tests import RunTestsSkill


# --- helpers (mirror the pytest-missing diagnostic fixtures) ------------------

def _clear_probe_cache(monkeypatch) -> None:
    """Isolate the memoized ``pytest_importable`` cache per test."""
    monkeypatch.setattr(run_tests_mod, "_PYTEST_IMPORTABLE", {})


def _patch_probe(monkeypatch, *, importable: bool) -> None:
    """Make the proactive ``import pytest`` probe deterministic (no subprocess).

    The shared guard ``verification_unavailable_interpreter`` (which
    ``compile_objective`` consults) imports ``pytest_importable`` from this module
    lazily, so patching it here is what makes the guard fire (or not)."""
    _clear_probe_cache(monkeypatch)
    monkeypatch.setattr(
        run_tests_mod, "pytest_importable", lambda python: importable)


# ``render`` / ``fetch`` are NON-public (absent from ``__all__``) so the public-API
# rail in ``_dead_param_moves`` permits dropping their dead params — a REAL move is
# available, so a missing guard WOULD land one (that is the bug under test).
_THREE_DEAD = (
    "__all__ = ['use']\n\n\n"
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=10) + fetch('u', retries=1)\n"
)


def _suited_project(tmp_path: Path, body: str = _THREE_DEAD) -> Path:
    """An external-shaped project WITH a real root-level pytest suite + a landable
    dead-param move — so ``_detect_commands`` emits a pytest command and the guard
    is genuinely reachable."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _suiteless_project(tmp_path: Path, body: str = _THREE_DEAD) -> Path:
    """A genuinely suite-less project: a landable move but NO pytest signal, so
    ``_detect_commands`` returns [] and the guard never even consults the probe."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    return tmp_path


# --- (a) pytest NOT importable → DECLINE up front, nothing landed -------------

def test_declines_up_front_when_pytest_unimportable(tmp_path, monkeypatch):
    root = _suited_project(tmp_path)
    before = (root / "app" / "m.py").read_text()
    # Sanity: this project DOES emit a pytest command (the guard is reachable).
    cmds = RunTestsSkill()._detect_commands(root)
    interp = cmds[0][0]

    _patch_probe(monkeypatch, importable=False)
    r = compile_objective(str(root), apply=True, verify=True)

    assert isinstance(r, CompileResult)
    # NOTHING landed — declined before any move work (never-fake-green).
    assert r.steps == []
    assert (root / "app" / "m.py").read_text() == before  # tree untouched
    # The loud, actionable message + the offending interpreter are carried.
    assert r.verification_unavailable
    assert "pytest is not importable" in r.verification_unavailable
    assert r.pytest_interpreter == interp


def test_declined_result_labels_verification_unavailable_not_no_suite(
        tmp_path, monkeypatch):
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=False)
    r = compile_objective(str(root), apply=True, verify=True)

    md = render_compile_markdown(r)
    # The distinct tier surfaces; the misleading no-suite line does NOT.
    assert "pytest is not importable" in md
    assert "no-suite — applied, nothing verified it" not in md
    # ...and the misleading "Applied 0 move(s): 0 verified" headline is suppressed.
    assert "0 verified" not in md

    data = r.to_dict()
    assert data["moves_applied"] == 0
    assert data["pytest_interpreter"]
    assert "pytest is not importable" in data["verification_unavailable"]


def test_compile_all_keeps_the_decline(tmp_path, monkeypatch):
    # ``--all`` bottoms out in ``compile_objective`` per objective; the decline must
    # not be silently dropped as "nothing to do".
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=False)
    results = compile_all(str(root), verify=True, apply=True)

    assert results, "the decline must be surfaced, not filtered out"
    assert all(r.steps == [] for r in results)
    assert all(r.verification_unavailable for r in results)


# --- (b) pytest IS importable → BYTE-IDENTICAL to today -----------------------

def test_pytest_importable_is_byte_identical(tmp_path, monkeypatch):
    # The guard returns None → the existing apply+verify path runs unchanged: the
    # move lands and verifies exactly as before (Apex's own env HAS pytest).
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=True)
    r = compile_objective(str(root), apply=True, verify=True)

    # The guard did NOT fire.
    assert not r.verification_unavailable
    assert r.pytest_interpreter == ""
    # The move landed and verified as before (the historical behaviour).
    assert len(r.steps) == 2
    assert r.fitness_start == 2.0 and r.fitness_end == 0.0
    assert all(s.verified for s in r.steps)
    assert all(not s.verification_unavailable for s in r.steps)
    src = (root / "app" / "m.py").read_text()
    assert "color" not in src and "retries" not in src


# --- (c) genuinely suite-less project → STILL "no-suite" ----------------------

def test_suiteless_project_still_reads_no_suite(tmp_path, monkeypatch):
    # A non-pytest / suite-less project is NOT verification-unavailable — the guard
    # returns None (no pytest command detected, probe never consulted) and the move
    # lands with the honest ``no-suite`` disclosure, exactly as before.
    root = _suiteless_project(tmp_path)
    # Even a probe that would say "unimportable" must not flip this — there is no
    # pytest command to be missing.
    _patch_probe(monkeypatch, importable=False)
    r = compile_objective(str(root), apply=True, verify=True)

    assert not r.verification_unavailable
    assert len(r.steps) == 2
    assert all(not s.verified for s in r.steps)
    assert all(not s.verification_unavailable for s in r.steps)
    md = render_compile_markdown(r)
    assert "no-suite — applied, nothing verified it" in md
    assert "pytest is not importable" not in md


# --- (d) --no-verify path is UNCHANGED (guard is verify-gated) ----------------

def test_no_verify_never_consults_the_guard(tmp_path, monkeypatch):
    # ``--no-verify`` already declares its moves UNVERIFIED by the user's choice, so
    # the guard must NOT fire (it would change that path). Make the probe explode if
    # consulted, then prove the run proceeds and lands as today.
    root = _suited_project(tmp_path)

    def _boom(python):
        raise AssertionError("probe consulted under --no-verify")

    _clear_probe_cache(monkeypatch)
    monkeypatch.setattr(run_tests_mod, "pytest_importable", _boom)
    r = compile_objective(str(root), apply=True, verify=False)

    assert not r.verification_unavailable
    assert len(r.steps) == 2  # lands exactly as before


def test_dry_run_never_consults_the_guard(tmp_path, monkeypatch):
    # A dry run (apply=False) does no suite work, so the guard is gated on
    # ``apply`` too — it must not fire (byte-identical dry-run listing).
    root = _suited_project(tmp_path)

    def _boom(python):
        raise AssertionError("probe consulted on a dry run")

    _clear_probe_cache(monkeypatch)
    monkeypatch.setattr(run_tests_mod, "pytest_importable", _boom)
    r = compile_objective(str(root), apply=False, verify=True)

    assert not r.verification_unavailable
    assert not r.applied
    assert len(r.steps) == 2  # lists what it WOULD land, as before


# --- defence-in-depth: the CompileStep flag + tier tag ------------------------

def test_step_flag_is_additive_and_tags_distinctly():
    # A pytest-present step omits the key (byte-identical); a pytest-missing step
    # carries it and tags DISTINCTLY from no-suite.
    from app.engine.objective_compiler import _compile_tier_tag

    plain = CompileStep(operator="o", target="m:f", description="d",
                        fitness_before=1.0, fitness_after=0.0)
    assert "verification_unavailable" not in plain.to_dict()
    assert "no-suite" in _compile_tier_tag(plain)

    unavailable = CompileStep(operator="o", target="m:f", description="d",
                              fitness_before=1.0, fitness_after=0.0,
                              verification_unavailable=True)
    assert unavailable.to_dict()["verification_unavailable"] is True
    tag = _compile_tier_tag(unavailable)
    assert "verification-unavailable" in tag
    assert "no-suite" not in tag


# --- (e) `apex develop --auto` (the THIRD aggregator) also surfaces the decline
# `_develop_auto` in cli_autonomy has its OWN result filter, independent of
# compile_all/compile_goal. It once dropped a verification-unavailable result
# (`if result.steps or result.fitness_start > 0`) → a false "Nothing to do:
# every objective is already at zero" instead of the loud message. This pins the
# third aggregator surfaces the decline too.

def test_develop_auto_surfaces_verification_unavailable_not_nothing_to_do(
        tmp_path, monkeypatch):
    import argparse
    import contextlib
    import io

    import app.cli_autonomy as ca

    root = _suited_project(tmp_path)
    # Pin the swept objective set to one cheap objective so the run is fast and
    # deterministic; the up-front decline in compile_objective fires regardless of
    # WHICH objective is selected (it precedes any move generation).
    monkeypatch.setattr(ca, "_select_for_sweep",
                        lambda *a, **k: ["wire-module-exports"])
    _patch_probe(monkeypatch, importable=False)

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    ca.register_parsers(sub)
    args = parser.parse_args(
        ["develop", "--auto", "--apply", "--target", str(root)])

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ca._develop_auto(args, root, grade_before=0.0, max_steps=8,
                              verify=True, apply=True)
    out = buf.getvalue()
    assert rc == 0
    # The loud, actionable message surfaces; the false "nothing to do" does NOT.
    assert "pytest is not importable" in out
    assert "already at zero" not in out
    assert "Nothing to do" not in out
    # And nothing was landed (declined before any move work).
    assert (root / "app" / "m.py").read_text() == _THREE_DEAD
