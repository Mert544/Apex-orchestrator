"""VERIFICATION-UNAVAILABLE DISCLOSURE PARITY — the SAME honesty gap commit
fa0218f closed in ONE aggregator (``cli_autonomy._develop_auto``), closed in its
SIX siblings.

``compile_objective`` DECLINES up front when the target has a pytest suite but
pytest is not importable under the interpreter Apex would invoke: it returns a
``CompileResult`` with ``verification_unavailable`` set + ZERO steps, landing
NOTHING (proof-carrying — can't verify => don't touch). Six aggregator loops over
``compile_objective`` SILENTLY DROPPED that decline — printing a false "nothing to
do / empty / already at zero" instead of surfacing the loud, actionable
"verification unavailable — pytest is not importable" message. That is a
never-fake-green honesty gap: the honest "can't verify here" disclosure was
swallowed.

This pins the fix for all six, mirroring
``tests/test_objective_compiler_verification_unavailable_eyml.py``'s fixture (a
project WITH a pytest suite + a monkeypatched ``pytest_importable`` -> False):

  1. ``dream_develop`` (``apex dream --land``) — the scoped landing chain.
  2. ``brief_develop`` (``apex brief --develop``) — the brief -> develop campaign.
  3. ``ascend`` (``apex ascend``) — the autonomous climb.
  4. ``chain_compiler`` (``apex chain``) — the explicit objective sequence.
  5. ``goal_fixpoint`` (``apex ... --fixpoint``) — the 1-leaf compile fallback.
  6. ``assist`` (``apex assist "<develop>"``) — the develop-route body.

Each test asserts the aggregator/CLI SURFACES the loud message (NOT a silent
"nothing to do"/"empty"/"already at zero") AND lands nothing, and each FAILS
without its fix (the assertions the pre-fix code violates are marked inline).

CRITICAL — DISCLOSURE ONLY: a project where pytest IS importable is byte-identical
(the decline never fires); each fix retains + surfaces an already-computed honest
decline; NONE make anything land. The probe is monkeypatched so no subprocess /
network / clock is involved — deterministic, stdlib + pytest only.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app.skills.execution.run_tests as run_tests_mod
from app.engine.ascend import ascend, render_ascend_markdown
from app.engine.brief_develop import develop_brief, render_brief_develop_markdown
from app.engine.chain_compiler import render_chain_markdown, run_chain
from app.engine.dream_develop import dream_develop, render_dream_chain_markdown
from app.engine.goal_fixpoint import render_fixpoint_markdown, run_goal_fixpoint


# --- helpers (mirror the compile-objective verification-unavailable fixture) ---

_UNAVAILABLE = "pytest is not importable"


def _patch_probe(monkeypatch, *, importable: bool) -> None:
    """Make the proactive ``import pytest`` probe deterministic (no subprocess).

    The shared guard ``verification_unavailable_interpreter`` (which
    ``compile_objective`` consults) imports ``pytest_importable`` from this module
    lazily, so patching it here is what makes the guard fire (or not)."""
    monkeypatch.setattr(run_tests_mod, "_PYTEST_IMPORTABLE", {})
    monkeypatch.setattr(
        run_tests_mod, "pytest_importable", lambda python: importable)


# A landable dead-param move under a REAL root-level pytest suite: ``_detect_commands``
# emits a pytest command (so the guard is genuinely reachable), and a missing guard
# WOULD land the move (that is the bug under test).
_THREE_DEAD = (
    "__all__ = ['use']\n\n\n"
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=10) + fetch('u', retries=1)\n"
)


def _suited_project(tmp_path: Path) -> Path:
    """An external-shaped project WITH a real root-level pytest suite + a landable
    dead-param move — so ``_detect_commands`` emits a pytest command and the guard
    is genuinely reachable."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(_THREE_DEAD, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _body(root: Path) -> str:
    return (root / "app" / "m.py").read_text(encoding="utf-8")


# --- 1. dream_develop (`apex dream --land`) -----------------------------------

def test_dream_develop_surfaces_decline_not_nothing_landable(tmp_path, monkeypatch):
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=False)

    report = dream_develop(str(root), apply=True)
    md = render_dream_chain_markdown(report)

    # Fix: the decline is RETAINED (dropped by the pre-fix ``campaign.steps or
    # fitness_start > 0`` filter) and its message is carried up.
    assert report.verification_unavailable
    assert _UNAVAILABLE in report.verification_unavailable
    # Fix: the renderer surfaces the loud message, NOT the false "nothing landable".
    assert _UNAVAILABLE in md
    assert "Nothing landable" not in md
    # Disclosure only: nothing landed (the decline never touches the tree).
    assert report.total_moves == 0
    assert _body(root) == _THREE_DEAD


# --- 2. brief_develop (`apex brief --develop`) --------------------------------

def _patch_brief(monkeypatch, root: Path):
    from app.engine.idea_brief import Brief
    brief = Brief(branch_path="dp.brief", title="dead params",
                  subject="app/m.py", operator="simplify",
                  evidence={"parameterize": [[3, "unused param"]]},
                  plan=[("simplify", ["parameterize"])])
    monkeypatch.setattr("app.engine.idea_brief.build_brief", lambda *a, **k: brief)


def test_brief_develop_surfaces_decline_not_zero_verified(tmp_path, monkeypatch):
    root = _suited_project(tmp_path)
    _patch_brief(monkeypatch, root)
    _patch_probe(monkeypatch, importable=False)

    result = develop_brief(str(root), branch_path="dp.brief", apply=True)
    assert result is not None
    md = render_brief_develop_markdown(result)

    # Fix: the decline is RETAINED (dropped by the pre-fix filter) + carried up.
    assert result.verification_unavailable
    assert _UNAVAILABLE in result.verification_unavailable
    # Fix: the renderer surfaces the loud message, NOT the false "0 verified move(s)".
    assert _UNAVAILABLE in md
    assert "verified move(s)" not in md
    # Disclosure only: nothing landed.
    assert result.total_moves == 0
    assert _body(root) == _THREE_DEAD


# --- 3. ascend (`apex ascend`) ------------------------------------------------

def test_ascend_surfaces_decline_not_develop_fixpoint(tmp_path, monkeypatch):
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=False)

    report = ascend(str(root), max_rounds=2, apply=True)
    md = render_ascend_markdown(report)

    # Fix: a zero-move decline is stamped as verification-unavailable (the pre-fix
    # code silently added it to ``blocked_run`` and fell through to a "fixpoint").
    assert report.verification_unavailable
    assert _UNAVAILABLE in report.verification_unavailable
    # Fix: the renderer surfaces the loud message, NOT the misleading fixpoint line.
    assert _UNAVAILABLE in md
    assert "already at a develop" not in md
    # ...and a decline is NOT a develop fixpoint (nothing was proven exhausted).
    assert report.fixpoint is False
    # Disclosure only: no rounds landed, tree untouched.
    assert report.rounds == []
    assert _body(root) == _THREE_DEAD


# --- 4. chain_compiler (`apex chain`) -----------------------------------------

def test_chain_surfaces_decline_on_empty_step_reason(tmp_path, monkeypatch):
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=False)

    report = run_chain(str(root), ["dead-params", "sort-imports"], apply=True)
    md = render_chain_markdown(report)

    # Fix: each empty step's ``reason`` carries the decline (pre-fix it stayed "").
    empties = [s for s in report.steps if s.status == "empty"]
    assert empties, "the declined objectives resolve to empty steps"
    assert all(_UNAVAILABLE in s.reason for s in empties)
    # Fix: the chain report DISCLOSES the loud message (render already surfaces
    # ``reason`` — before the fix it printed a silent "empty" with no reason).
    assert _UNAVAILABLE in md
    # Disclosure only: nothing landed.
    assert report.total_moves == 0
    assert _body(root) == _THREE_DEAD


# --- 5. goal_fixpoint (`--fixpoint`, 1-leaf compile fallback) ------------------

def test_goal_fixpoint_surfaces_decline_on_empty_round_reason(
        tmp_path, monkeypatch):
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=False)

    report = run_goal_fixpoint(str(root), ["dead-params"], apply=True)
    md = render_fixpoint_markdown(report)

    # Fix: the 1-leaf ``_land_via_compile`` empty round carries the decline on
    # ``reason`` (pre-fix it returned ``status="empty"`` with no reason at all).
    empties = [r for rd in report.rounds for r in rd.results
               if r.status == "empty"]
    assert empties, "the declined goal resolves to an empty round"
    assert all(_UNAVAILABLE in r.reason for r in empties)
    # Fix: the fixpoint report DISCLOSES the loud message (render already surfaces
    # ``reason``).
    assert _UNAVAILABLE in md
    # Disclosure only: nothing landed.
    assert report.total_landed == 0
    assert _body(root) == _THREE_DEAD


# --- 6. assist (`apex assist "<develop>"`) ------------------------------------

def test_assist_develop_surfaces_decline_not_zero_moves(tmp_path, monkeypatch):
    from app.agent.assist import _render_develop
    from app.engine.objective_compiler import compile_objective

    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=False)

    # Drive the SAME compiler the assist develop route bottoms out in, then render
    # the develop-route body over its result (a decline campaign).
    campaign = compile_objective(str(root), objective="dead-params",
                                 apply=True, verify=True)
    result = SimpleNamespace(
        payload={"write": True, "objectives": ["dead-params"],
                 "capped": False, "scope": None},
        _results=[campaign])
    lines = _render_develop(result)
    body = "\n".join(lines)

    # The compiler declined (the guard fired), landing nothing.
    assert campaign.verification_unavailable
    assert campaign.steps == []
    # Fix: the develop-route body surfaces the loud message, NOT the false
    # "0 verified move(s)" / "Preview: 0 move(s)" line the pre-fix render printed.
    assert _UNAVAILABLE in body
    assert "verified move(s)" not in body
    # Disclosure only: the tree is untouched.
    assert _body(root) == _THREE_DEAD


# --- byte-identity guard: pytest IMPORTABLE => the decline never fires ---------

def test_pytest_importable_never_declines_across_aggregators(tmp_path, monkeypatch):
    # When pytest IS importable the guard returns None everywhere, so NONE of the
    # six aggregators carry a decline — the disclosure paths are strictly additive.
    root = _suited_project(tmp_path)
    _patch_probe(monkeypatch, importable=True)

    dream = dream_develop(str(root), apply=True)
    assert not dream.verification_unavailable

    climb = ascend(str(root), max_rounds=1, apply=True)
    assert not climb.verification_unavailable

    chain = run_chain(str(root), ["dead-params"], apply=True)
    assert all(_UNAVAILABLE not in (s.reason or "") for s in chain.steps)

    fix = run_goal_fixpoint(str(root), ["dead-params"], apply=True)
    assert all(_UNAVAILABLE not in (r.reason or "")
               for rd in fix.rounds for r in rd.results)
