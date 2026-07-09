"""``apex quickstart`` — the 60-second on-ramp, as ONE read-only motion.

Composes ONLY existing engines (``health_score.grade`` plus the same bounded
idea/roadmap scout ``apex auto`` uses) — invents no new analysis. These tests
pin the contract:

  * end-to-end human output carries the health grade, the honestly-labeled
    "bounded quickstart scout" landable line, and the three copy-paste next
    steps;
  * ``--json`` emits the documented structured dict, including
    ``suite_detected``;
  * STRICTLY READ-ONLY: the target tree (and any ``.apex/``) is byte-for-byte
    unchanged after running, on both the human and ``--json`` paths;
  * a fresh/near-empty project never raises and reports 0 landable moves;
  * determinism: two runs on the same project produce byte-identical output;
  * the command is registered and dispatches to ``cmd_quickstart``.

2026-07-08 honesty fix (audit finding 6, buyer-facing L1): ``landable_count``
comes from a SEPARATE, budget-capped scout
(``IdeaActionBridge.plan_roadmap`` over a 20-idea/depth-1/breadth-3 idea tree)
that genuinely diverges from what ``apex develop session`` enumerates (a live
run on this repo: 17 vs. 76). Unifying the two engines — sourcing the count
from ``run_develop_session(apply=False)`` — was tried and REJECTED on
measured evidence: 120s even bounded to ``max_steps=1``, 5+ minutes unbounded
on a 630-module repo, which breaks the 60-second on-ramp promise outright.
The fix is in the LABEL: the rendered line names the number as the bounded
scout's count and points to ``apex develop`` for the full enumeration, so no
equality between the two engines is ever claimed
(``test_quickstart_landable_line_names_scout_and_defers_to_develop``), and
quickstart structurally never invokes the session engine
(``test_quickstart_does_not_run_develop_session``). The wording is also keyed
off whether a test suite is DETECTABLE (``_quickstart_suite_detected``): it
promises test-verification on ``--apply`` only when a suite exists, and says
so honestly (no-suite tier, unverified) when it does not — never
over-promising verification a suite-less project cannot earn.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from app.cli_insight import cmd_quickstart


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _build_project(root: Path) -> None:
    """A small, real Python project: a couple of modules plus a linked test —
    enough for the grade + idea engines to have something to say."""
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "mod.py").write_text(
        "def add(x, y):\n"
        "    return x + y\n",
        encoding="utf-8")
    (root / "app" / "other.py").write_text(
        "def greet(name):\n"
        "    return f'hi {name}'\n",
        encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_mod.py").write_text(
        "from app.mod import add\n\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'p'\nversion = '0'\n", encoding="utf-8")


def _ns(target: str, as_json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(target=target, json=as_json)


def _snapshot(root: Path) -> set[tuple[str, bytes]]:
    """Every file under ``root`` (path, content) — including any ``.apex/`` —
    so a stray write of any kind is caught, not just a git-visible one."""
    return {
        (str(p.relative_to(root)), p.read_bytes())
        for p in sorted(root.rglob("*")) if p.is_file()
    }


# --------------------------------------------------------------------------- #
# End-to-end human output
# --------------------------------------------------------------------------- #

def test_quickstart_end_to_end_human_output(tmp_path, capsys):
    _build_project(tmp_path)
    rc = cmd_quickstart(_ns(str(tmp_path)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Zero-token · offline · deterministic · never-fake-green." in out
    assert "## Health:" in out
    # The landable line names its source (the bounded scout) and defers to
    # `apex develop` for the full enumeration — never an unattributed count.
    assert "move(s) found by the bounded quickstart scout" in out
    assert "full enumeration: `apex develop` (preview)" in out
    # `_build_project` gives the project a detectable suite (tests/ +
    # pyproject.toml) — the honest wording must promise test-verification,
    # never the no-suite disclosure.
    assert ("each lands test-verified on --apply "
            "(suite-gated, auto-rollback)") in out
    assert "no test suite detected" not in out
    assert f"apex grade --target {tmp_path} --diff" in out
    assert f"apex develop --target {tmp_path} --apply" in out
    assert f"apex dashboard --target {tmp_path}" in out


def test_quickstart_default_target_renders_dot(tmp_path, capsys, monkeypatch):
    # No --target given: the next-step commands stay copy-paste valid by
    # falling back to `.` rather than an absolute path.
    _build_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = cmd_quickstart(_ns(""))
    out = capsys.readouterr().out
    assert rc == 0
    assert "apex grade --target . --diff" in out
    assert "apex develop --target . --apply" in out
    assert "apex dashboard --target ." in out


# --------------------------------------------------------------------------- #
# --json contract
# --------------------------------------------------------------------------- #

def test_quickstart_json_has_documented_keys(tmp_path, capsys):
    _build_project(tmp_path)
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(data) == {
        "grade", "breakdown", "top_opportunities", "landable_count",
        "suite_detected", "next_steps",
    }
    assert set(data["grade"]) == {"score", "letter"}
    assert isinstance(data["grade"]["score"], int)
    assert isinstance(data["breakdown"], str) and data["breakdown"]
    assert isinstance(data["top_opportunities"], list)
    assert len(data["top_opportunities"]) <= 3
    for op in data["top_opportunities"]:
        assert set(op) == {"branch_path", "title", "phase", "roi"}
    assert isinstance(data["landable_count"], int) and data["landable_count"] >= 0
    assert data["suite_detected"] is True  # `_build_project` has tests/ + pyproject.toml
    assert data["next_steps"] == [
        f"apex grade --target {tmp_path} --diff",
        f"apex develop --target {tmp_path} --apply",
        f"apex dashboard --target {tmp_path}",
    ]


# --------------------------------------------------------------------------- #
# Honest attribution of the landable count (the honesty fix, in the LABEL)
# --------------------------------------------------------------------------- #

def test_quickstart_landable_line_names_scout_and_defers_to_develop():
    """The landable line must (a) NAME its source — the bounded quickstart
    scout, a different engine than ``apex develop session``'s enumeration —
    and (b) point to ``apex develop`` for the full count, in BOTH suite
    states. This is the honest resolution of the two engines' genuine
    divergence (live: 17 vs. 76): unification was measured at 120s+ (breaks
    the 60-second on-ramp), so the equality claim is removed instead of the
    engines being merged."""
    from app.cli_insight import _quickstart_landable_line

    with_suite = _quickstart_landable_line(6, suite_detected=True)
    assert "6 move(s) found by the bounded quickstart scout" in with_suite
    assert "full enumeration: `apex develop` (preview)" in with_suite
    assert "test-verified on --apply" in with_suite

    without_suite = _quickstart_landable_line(6, suite_detected=False)
    assert "6 move(s) found by the bounded quickstart scout" in without_suite
    assert "enumeration: `apex develop` (preview)" in without_suite
    assert "no test suite detected" in without_suite
    # Never an unattributed bare count in either state.
    for line in (with_suite, without_suite):
        assert "move(s) available" not in line


def test_quickstart_does_not_run_develop_session(tmp_path, capsys, monkeypatch):
    """STRUCTURAL pin of the rejected unification: quickstart must never
    invoke ``run_develop_session`` — that pass measured 120s even at
    ``max_steps=1`` (5+ min unbounded) on a 630-module repo, destroying the
    60-second promise. If any future change re-wires ``landable_count`` to
    the session engine, this booby-trap makes the run fail loudly instead of
    silently re-landing the regression."""
    import app.engine.develop_session as develop_session

    def _forbidden(*a, **k):
        raise AssertionError(
            "quickstart must not run the develop-session enumeration "
            "(measured 120s+ — see _quickstart_landable)")

    monkeypatch.setattr(develop_session, "run_develop_session", _forbidden)
    _build_project(tmp_path)
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(data["landable_count"], int)
    assert data["landable_count"] >= 0


# --------------------------------------------------------------------------- #
# Honest wording per suite state
# --------------------------------------------------------------------------- #

def test_quickstart_no_suite_wording_never_promises_verification(tmp_path, capsys):
    # Source but no detectable test suite: no `tests/` dir, no pytest config,
    # no `pyproject.toml`, no flat `test_*.py` — `_quickstart_suite_detected`
    # must read this honestly and the rendered line must never claim
    # test-verification a suite-less project cannot earn.
    (tmp_path / "mod.py").write_text(
        "def add(x, y):\n    return x + y\n", encoding="utf-8")
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["suite_detected"] is False

    rc = cmd_quickstart(_ns(str(tmp_path)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "no test suite detected" in out
    assert "moves would land unverified (no-suite tier)" in out
    assert "test-verified" not in out


# --------------------------------------------------------------------------- #
# READ-ONLY
# --------------------------------------------------------------------------- #

def test_quickstart_never_writes_to_target_tree(tmp_path, capsys):
    _build_project(tmp_path)
    before = _snapshot(tmp_path)
    cmd_quickstart(_ns(str(tmp_path)))
    capsys.readouterr()
    cmd_quickstart(_ns(str(tmp_path), as_json=True))
    capsys.readouterr()
    after = _snapshot(tmp_path)
    assert before == after
    assert not (tmp_path / ".apex").exists()


# --------------------------------------------------------------------------- #
# Honest on a fresh/empty project
# --------------------------------------------------------------------------- #

def test_quickstart_on_empty_project_never_raises(tmp_path, capsys):
    # No files at all — the barest possible "fresh project".
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["landable_count"] == 0
    assert data["suite_detected"] is False
    assert data["grade"]["score"] == 100
    assert data["grade"]["letter"] == "A+"
    assert isinstance(data["top_opportunities"], list)


def test_quickstart_engine_failure_degrades_to_honest_empty(tmp_path, capsys, monkeypatch):
    # If the idea engine itself raises (a hostile/unreadable project), the
    # command must still exit 0 with an honest, empty opportunity picture
    # rather than crashing the on-ramp. `landable_count` reads off the same
    # scout report (None here), so it collapses to the honest 0 too.
    class _BoomEngine:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")

    import app.engine.idea_permutation as idea_permutation

    monkeypatch.setattr(idea_permutation, "IdeaPermutationEngine", _BoomEngine)
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["top_opportunities"] == []
    assert data["landable_count"] == 0


def test_quickstart_bridge_failure_degrades_landable_to_honest_zero(
        tmp_path, capsys, monkeypatch):
    # If the roadmap bridge itself raises, `landable_count` must degrade to 0
    # honestly rather than crashing the on-ramp — and a single engine's
    # failure never takes down the rest of the report.
    _build_project(tmp_path)

    class _BoomBridge:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")

    import app.engine.idea_action_bridge as idea_action_bridge

    monkeypatch.setattr(idea_action_bridge, "IdeaActionBridge", _BoomBridge)
    rc = cmd_quickstart(_ns(str(tmp_path), as_json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["landable_count"] == 0
    assert data["grade"]["letter"]


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #

def test_quickstart_is_deterministic(tmp_path, capsys):
    _build_project(tmp_path)
    cmd_quickstart(_ns(str(tmp_path), as_json=True))
    first = capsys.readouterr().out
    cmd_quickstart(_ns(str(tmp_path), as_json=True))
    second = capsys.readouterr().out
    assert first == second

    cmd_quickstart(_ns(str(tmp_path)))
    first_md = capsys.readouterr().out
    cmd_quickstart(_ns(str(tmp_path)))
    second_md = capsys.readouterr().out
    assert first_md == second_md


# --------------------------------------------------------------------------- #
# Registration / dispatch
# --------------------------------------------------------------------------- #

def test_quickstart_is_registered_and_dispatches():
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "quickstart" in sub.choices
    assert sub.choices["quickstart"].get_default("func") is cli_insight.cmd_quickstart


def test_quickstart_help_does_not_raise():
    with pytest.raises(SystemExit) as exc:
        import sys
        from unittest import mock

        with mock.patch.object(sys, "argv", ["apex", "quickstart", "--help"]):
            from app.cli import main

            main()
    assert exc.value.code == 0
