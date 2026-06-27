"""SAFE-by-default autonomous --apply: the broad sweep lands ONLY covered moves.

The buyer-proof regression this pins: `apex develop --auto --apply` (and `apex
auto --apply`) used to land a WEAK/uncovered move — one whose green suite NO test
exercises, so a green run can't vouch for it — which is how a sweep dropped a
package's public API on a green suite. And `apex auto` auto-applied even WITHOUT
`--apply` on a clean tree (a footgun that once edited Apex's own repo).

Covered here (each new assertion verified to FAIL pre-change):
  * a sweep with one COVERED + one WEAK move lands ONLY the covered one by
    default; the weak one is PREVIEWED (``CompileResult.withheld``) but its file
    is left untouched (rolled back);
  * ``--allow-weak`` lands BOTH — and the applied bytes are IDENTICAL to today's
    baseline (``covered_only`` off);
  * the human report MESSAGES the withheld count + that ``--allow-weak`` lands
    them;
  * a per-objective explicit ``develop --objective X --apply`` still lands the
    chosen objective's weak move (the user chose it — covered-only is sweep-only);
  * ``apex auto`` with NO ``--apply`` writes NOTHING on a clean tree (spy:
    ``IdeaActionBridge.apply_plan`` is never reached / the gate previews);
  * the AutonomyPolicy ``require_explicit_apply`` gate previews without ``--apply``
    and is byte-identical (off) for the unattended daemon path.

Real engine on disposable fixtures (mirrors the develop-session / autonomous-
synthesis eyml style); no time/random/order assertions.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import cmd_auto, cmd_develop


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
def _covered_and_weak_project(root: Path) -> Path:
    """A package with TWO ``== None`` idioms (both ``modernize`` candidates):

      * ``pkg/covered.py`` — a test imports + exercises it (COVERED ⇒ verified);
      * ``pkg/weak.py``    — NO test references it (a green full suite can't vouch
        for a change here ⇒ WEAK / coverage ``none``).

    Deterministic: the only debt is the two idioms, so the cheap ``modernize``
    sweep selects exactly these two moves — one covered, one weak."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "covered.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_covered.py").write_text(
        "from pkg.covered import is_missing\n"
        "def test_m():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    (root / "pkg" / "weak.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")
    return root


def _develop_ns(target: Path, **over) -> argparse.Namespace:
    base = dict(
        target=str(target), objective="dead-params", goal="", auto=True,
        concrete=False, allow_weak=False, all_objectives=False, grade=False,
        history=False, from_dream=False, deep=False, playbook=False, top=False,
        session=False, mode_word="", apply=False, max_steps=8, no_verify=False,
        fast=False, min_value=None, value_led=False, force=False, shield=False,
        json=False)
    base.update(over)
    return argparse.Namespace(**base)


def _auto_ns(target: Path, **over) -> argparse.Namespace:
    base = dict(
        goal="", target=str(target), apply=False, allow_weak=False,
        recommend=False, mode=None, commit=False, deep=False, no_verify=False,
        max_apply=0, json=False, out="")
    base.update(over)
    return argparse.Namespace(**base)


def _run(fn, ns: argparse.Namespace) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(ns)
    return rc, out.getvalue()


def _covered_idiom(root: Path) -> str:
    return (root / "pkg" / "covered.py").read_text()


def _weak_idiom(root: Path) -> str:
    return (root / "pkg" / "weak.py").read_text()


# --------------------------------------------------------------------------- #
# develop --auto --apply : covered-only by default                            #
# --------------------------------------------------------------------------- #
def test_develop_auto_apply_lands_only_covered_move_by_default(tmp_path: Path):
    _covered_and_weak_project(tmp_path)
    rc, _out = _run(cmd_develop, _develop_ns(tmp_path, apply=True))
    assert rc == 0
    # The COVERED move landed (a test exercises it) ...
    assert "value is None" in _covered_idiom(tmp_path)
    assert "== None" not in _covered_idiom(tmp_path)
    # ... and the WEAK move was WITHHELD: its file is untouched (rolled back).
    assert "== None" in _weak_idiom(tmp_path)


def test_develop_auto_apply_messages_the_withheld_move(tmp_path: Path):
    _covered_and_weak_project(tmp_path)
    rc, out = _run(cmd_develop, _develop_ns(tmp_path, apply=True))
    assert rc == 0
    # Clear, actionable messaging: how many were withheld + how to land them.
    assert "Withheld" in out
    assert "--allow-weak" in out


def test_develop_auto_allow_weak_lands_both_moves(tmp_path: Path):
    _covered_and_weak_project(tmp_path)
    rc, _out = _run(cmd_develop, _develop_ns(tmp_path, apply=True, allow_weak=True))
    assert rc == 0
    # --allow-weak restores land-everything: BOTH idioms are modernized.
    assert "value is None" in _covered_idiom(tmp_path)
    assert "value is None" in _weak_idiom(tmp_path)
    assert "== None" not in _weak_idiom(tmp_path)


def test_develop_auto_allow_weak_apply_is_byte_identical_to_baseline(tmp_path: Path):
    """``--allow-weak`` (covered_only OFF) must land EXACTLY what today lands —
    byte-for-byte. The baseline drives the SAME sweep (same selected objectives,
    same compile loop) but with NO covered-only gate at all (the literal
    pre-change call), then compares every file in the two trees."""
    from app.engine.objective_compiler import compile_objective
    from app.cli_autonomy import _auto_selected_objectives

    # Baseline tree: run the identical autonomous selection + compile loop, but
    # WITHOUT passing covered_only (the round-21-safe, pre-change behaviour).
    base = tmp_path / "baseline"
    base.mkdir()
    _covered_and_weak_project(base)
    for obj in _auto_selected_objectives(base, False):
        compile_objective(str(base), objective=obj, apply=True, verify=True,
                          max_steps=8)

    # --allow-weak tree via the CLI sweep (covered_only OFF).
    cli = tmp_path / "cli"
    cli.mkdir()
    _covered_and_weak_project(cli)
    _run(cmd_develop, _develop_ns(cli, apply=True, allow_weak=True))

    # Every source file lands byte-for-byte identically to the baseline.
    for rel in ("pkg/covered.py", "pkg/weak.py", "pkg/__init__.py"):
        assert (cli / rel).read_text() == (base / rel).read_text(), rel
    # And the baseline genuinely landed the weak move (so this is a real check).
    assert "value is None" in (base / "pkg" / "weak.py").read_text()


def test_develop_auto_dry_run_writes_nothing(tmp_path: Path):
    _covered_and_weak_project(tmp_path)
    rc, out = _run(cmd_develop, _develop_ns(tmp_path, apply=False))
    assert rc == 0
    # Dry run: both idioms still present, nothing written, nothing withheld-rolled.
    assert "== None" in _covered_idiom(tmp_path)
    assert "== None" in _weak_idiom(tmp_path)
    assert "Applied to your working tree" not in out


def test_develop_auto_apply_json_marks_withheld_additively(tmp_path: Path):
    _covered_and_weak_project(tmp_path)
    rc, out = _run(cmd_develop, _develop_ns(tmp_path, apply=True, json=True))
    assert rc == 0
    data = json.loads(out.strip())
    modernize = next(r for r in data if r["objective"] == "modernize")
    # The covered move is a landed step; the weak one is surfaced under withheld.
    assert modernize["moves_applied"] == 1
    assert any("weak.py" in w for w in modernize.get("withheld", []))


# --------------------------------------------------------------------------- #
# per-objective explicit apply : the user chose it, weak move still lands       #
# --------------------------------------------------------------------------- #
def test_explicit_objective_apply_still_lands_weak_move(tmp_path: Path):
    """A user who NAMES an objective explicitly (``develop --objective modernize
    --apply``) is not on the broad sweep — their chosen weak move still lands
    (covered-only is sweep-only safety, never a per-objective veto)."""
    _covered_and_weak_project(tmp_path)
    ns = _develop_ns(tmp_path, auto=False, objective="modernize", apply=True)
    rc, _out = _run(cmd_develop, ns)
    assert rc == 0
    # BOTH land — including the uncovered weak module — because the user chose it.
    assert "value is None" in _weak_idiom(tmp_path)
    assert "== None" not in _weak_idiom(tmp_path)


# --------------------------------------------------------------------------- #
# apex auto : PREVIEW by default — no --apply, no writes (the footgun fix)      #
# --------------------------------------------------------------------------- #
def test_auto_without_apply_writes_nothing_on_clean_tree(tmp_path: Path, monkeypatch):
    """The footgun: a bare ``apex auto`` on a CLEAN tree used to auto-apply. Now
    it PREVIEWS — ``apply_plan`` is never reached, so nothing is written."""
    _covered_and_weak_project(tmp_path)
    # Force the clean-tree precondition the old footgun fired on.
    monkeypatch.setattr(m, "_working_tree_clean", lambda target: True)
    calls: list[str] = []
    from app.engine.idea_action_bridge import IdeaActionBridge
    real_apply = IdeaActionBridge.apply_plan

    def _spy(self, *a, **k):
        calls.append("apply_plan")
        return real_apply(self, *a, **k)

    monkeypatch.setattr(IdeaActionBridge, "apply_plan", _spy)

    rc, out = _run(cmd_auto, _auto_ns(tmp_path, apply=False))
    assert rc == 0
    # The gated writer was NEVER called, and nothing on disk changed.
    assert calls == []
    assert "== None" in _covered_idiom(tmp_path)
    assert "== None" in _weak_idiom(tmp_path)
    # It tells the user how to actually apply.
    assert "--apply" in out


def test_auto_with_apply_still_acts(tmp_path: Path, monkeypatch):
    """``apex auto --apply`` still applies (the explicit opt-in is unchanged) —
    landing at least the covered move, suite-verified."""
    _covered_and_weak_project(tmp_path)
    monkeypatch.setattr(m, "_working_tree_clean", lambda target: True)
    rc, _out = _run(cmd_auto, _auto_ns(tmp_path, apply=True))
    assert rc == 0
    # The covered modernize move landed on the working tree.
    assert "value is None" in _covered_idiom(tmp_path)
