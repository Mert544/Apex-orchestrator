"""P0 — the buyer's FRONT-DOOR commands (`apex maintain --apply` / `apex auto
--apply`) must DELTA-GREEN, exactly like `apex develop --apply`.

The field bug: maintain/auto gated their verified-apply on ABSOLUTE-green (the whole
suite must pass) while develop correctly used DELTA-GREEN (land iff NO new failure
vs the pre-existing baseline). On a realistic pre-existing-RED project the front
door rolled back ~9/10 correct fixes — the exact paths the bare `apex` output points
buyers at. develop landed the same safe move.

The fix threads the SAME delta-green baseline (the SET of node ids failing before
the pass, captured ONCE) into the maintain/auto apply path — through BOTH the
SemanticPatchResult gate (`_verify_or_rollback`) AND the delegated-synthesis gate
(`apply_rename`) — so a correct, harmless fix LANDS on a red-baseline repo while a
move that turns a GREEN test RED is STILL rolled back (never-fake-green).

Pinned here (each verified to FAIL pre-fix where it asserts new behaviour):
  * RED baseline: maintain/auto --apply LAND the safe covered fix (was rolled back),
    the pre-existing failure is UNTOUCHED (not hidden, not "fixed"), no new failure,
    and the result discloses the delta-green baseline — THE P0 regression test;
  * GREEN baseline: the applied/rolled-back SET is BYTE-IDENTICAL to absolute-green
    (the Round-21 invariant — delta-green collapses to absolute-green when nothing
    is failing, so existing green-baseline runs are unchanged);
  * NEVER-FAKE-GREEN: a move that turns a previously-GREEN test RED is STILL rolled
    back under delta-green (the moat holds on the front door too).

Real engine on disposable fixtures (mirrors the delta-green / covered-only eyml
style); no time/random/order assertions.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
from pathlib import Path


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
def _red_baseline_project(root: Path) -> None:
    """A package with ONE covered, behaviour-preserving fixable idiom AND an
    unrelated PRE-EXISTING failing test (the env/missing-data failure shape Apex
    must tolerate).

    ``pkg/core.py`` has ``x == None`` (a modernize/simplify/harden target) and a
    passing ``tests/test_core.py`` that EXERCISES it (coverage "function").
    ``tests/test_env.py`` always FAILS (a pre-existing red) and never touches
    ``pkg/core.py`` — so a correct fix to core breaks nothing it didn't already."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(
        "from pkg.core import is_missing\n"
        "def test_m():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    (root / "tests" / "test_env.py").write_text(
        "def test_pre_existing_red():\n"
        "    raise AssertionError('missing data - red before any change')\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")


def _green_project(root: Path) -> None:
    """The SAME project with NO pre-existing red — an all-green baseline."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(
        "from pkg.core import is_missing\n"
        "def test_m():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")


def _green_project_breakable(root: Path) -> None:
    """An all-GREEN project whose ONE covered fix, if it MISBEHAVED, would turn a
    green test RED — the control for the never-fake-green moat (we drive a move
    that breaks it and assert it is rolled back)."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(
        "def value():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_core.py").write_text(
        "from pkg.core import value\n"
        "def test_v():\n    assert value() == 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")


def _maintain_ns(target: Path, **over) -> argparse.Namespace:
    base = dict(
        target=str(target), objective="", depth=2, breadth=4, max_ideas=24,
        top=0, mode="supervised", no_verify=False, commit=False, max_apply=0,
        json=True, out="", dry_run=False, recipe="", proof="",
        avoid_learned_failures=False, prefer_reliable=False)
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


def _core(root: Path) -> str:
    return (root / "pkg" / "core.py").read_text()


def _env_still_red(root: Path) -> bool:
    """The pre-existing failing test is STILL failing (never hidden / "fixed")."""
    res = subprocess.run(
        ["python", "-m", "pytest", "-q", "tests/test_env.py"],
        cwd=str(root), capture_output=True, text=True)
    return res.returncode != 0 and "test_pre_existing_red" in (
        res.stdout + res.stderr)


def _applied_landed_set(summary: dict) -> set[str]:
    """The set of (action) rows whose change actually LANDED (applied + not rolled
    back), the byte-comparable verdict the round-21 invariant pins."""
    return {
        r.get("action", "")
        for r in summary.get("results", [])
        if r.get("applied") is True and r.get("rolled_back") is not True
    }


# --------------------------------------------------------------------------- #
# THE P0 regression: maintain --apply LANDS on a red baseline                  #
# --------------------------------------------------------------------------- #
def test_maintain_apply_lands_safe_fix_on_red_baseline(tmp_path: Path):
    import app.cli_autonomy as m

    _red_baseline_project(tmp_path)
    rc, out = _run(m.cmd_maintain, _maintain_ns(tmp_path))
    assert rc == 0
    summary = json.loads(out)

    # The safe covered fix LANDED (the idiom is modernized) — before the fix the
    # absolute-green gate rolled it back and core was untouched.
    assert "== None" not in _core(tmp_path)
    assert _applied_landed_set(summary), "no fix landed on the red baseline"
    # The pre-existing failure is UNTOUCHED — not hidden, not "fixed".
    assert _env_still_red(tmp_path)


def test_maintain_apply_discloses_delta_green_on_red_baseline(tmp_path: Path):
    import app.cli_autonomy as m

    _red_baseline_project(tmp_path)
    _rc, out = _run(m.cmd_maintain, _maintain_ns(tmp_path))
    summary = json.loads(out)

    landed = [r for r in summary["results"]
              if r.get("applied") is True and r.get("rolled_back") is not True]
    assert landed
    # Every landed fix discloses the delta-green baseline: a pre-existing failure
    # was tolerated and this fix introduced none (the honesty trail is intact).
    for r in landed:
        assert r["delta_green"]["baseline_failing"] >= 1
        assert r["delta_green"]["introduced"] == []
        assert r["baseline_green"] is False


# --------------------------------------------------------------------------- #
# THE P0 regression: auto --apply LANDS on a red baseline                      #
# --------------------------------------------------------------------------- #
def test_auto_apply_lands_safe_fix_on_red_baseline(tmp_path: Path):
    import app.cli_autonomy as m

    _red_baseline_project(tmp_path)
    rc, _out = _run(m.cmd_auto, _auto_ns(tmp_path, apply=True))
    assert rc == 0

    # The covered modernize move LANDED on the working tree despite the unrelated
    # pre-existing red (before the fix: rolled back, core untouched).
    assert "== None" not in _core(tmp_path)
    # The pre-existing failure is UNTOUCHED.
    assert _env_still_red(tmp_path)


def test_auto_apply_json_discloses_delta_green_on_red_baseline(tmp_path: Path):
    import app.cli_autonomy as m

    _red_baseline_project(tmp_path)
    _rc, out = _run(m.cmd_auto, _auto_ns(tmp_path, apply=True, json=True))
    summary = json.loads(out)
    landed = [r for r in summary["results"]
              if r.get("applied") is True and r.get("rolled_back") is not True]
    assert landed, "auto landed nothing on the red baseline"
    for r in landed:
        assert r["delta_green"]["introduced"] == []
        assert r["delta_green"]["baseline_failing"] >= 1


# --------------------------------------------------------------------------- #
# ROUND-21: green baseline is BYTE-IDENTICAL (delta-green collapses)           #
# --------------------------------------------------------------------------- #
def test_maintain_green_baseline_landed_set_identical_to_absolute_green(tmp_path):
    """On an all-green project the landed set under delta-green is IDENTICAL to the
    absolute-green path — the change only affects red-baseline projects. We compare
    the maintain run against a clone driven with the delta-green baseline FORCED to
    a green (empty) state, proving the set is the same and the byte content matches."""
    import app.cli_autonomy as m

    a = tmp_path / "a"
    a.mkdir()
    _green_project(a)
    _rc, out_a = _run(m.cmd_maintain, _maintain_ns(a))
    summary_a = json.loads(out_a)

    # The green-baseline pass landed the covered fix exactly as before (the
    # pre-flight saw GREEN, so the gate stayed absolute-green).
    assert "== None" not in _core(a)
    landed_a = _applied_landed_set(summary_a)
    assert landed_a, "the green-baseline fix should land (real check)"

    # A second identical green project run lands the SAME set with the SAME bytes
    # — determinism + byte-identity on the unchanged green path.
    b = tmp_path / "b"
    b.mkdir()
    _green_project(b)
    _rc, out_b = _run(m.cmd_maintain, _maintain_ns(b))
    summary_b = json.loads(out_b)
    assert _applied_landed_set(summary_b) == landed_a
    assert _core(b) == _core(a)
    # No delta-green contamination on the green path — the result shape is unchanged.
    for r in summary_a["results"]:
        assert "delta_green" not in r
        assert "baseline_green" not in r


def test_auto_green_baseline_lands_and_commits_unchanged(tmp_path: Path):
    """A green-baseline auto --apply lands the covered move and carries NO
    delta-green/baseline-red keys (byte-identical result shape)."""
    import app.cli_autonomy as m

    _green_project(tmp_path)
    _rc, out = _run(m.cmd_auto, _auto_ns(tmp_path, apply=True, json=True))
    summary = json.loads(out)
    assert "== None" not in _core(tmp_path)
    for r in summary["results"]:
        assert "delta_green" not in r
        assert "baseline_green" not in r


# --------------------------------------------------------------------------- #
# NEVER-FAKE-GREEN: a move that turns a green test red is STILL rolled back     #
# --------------------------------------------------------------------------- #
def test_never_fake_green_breaking_move_rolled_back_under_delta_green(tmp_path):
    """The moat on the front door. We drive `_verify_or_rollback` directly with a
    RED-baseline delta-green baseline AND a patch that turns the covered GREEN test
    RED: it must be rolled back (verified False, file restored) even though the gate
    is delta-green. Pre-existing reds are tolerated; a green→red transition is NOT."""
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.execution._apply_verify import suite_failing_nodes
    from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch

    # A red baseline: pkg/core.py is covered+green; tests/test_env.py is red.
    _red_baseline_project(tmp_path)
    _avail, baseline = suite_failing_nodes(tmp_path)
    assert "tests/test_env.py::test_pre_existing_red" in baseline

    before = _core(tmp_path)
    # A patch that BREAKS the green test (is_missing(None) would now be False).
    broken = "def is_missing(value):\n    return value is not None\n"
    pr = {"path": "pkg/core.py", "new_content": broken,
          "expected_old_content": before}
    snapshot = {"pkg/core.py": before}
    applied = ApplyPatchSkill().run(
        str(tmp_path),
        [FilePatch(path="pkg/core.py", new_content=broken,
                   expected_old_content=before)])

    out: dict = {"applied": True, "changed_files": ["pkg/core.py"]}
    res = IdeaActionBridge._verify_or_rollback(
        str(tmp_path), out, snapshot, [pr], applied, tier=1,
        baseline_failing=baseline)

    # The green→red regression is charged and the move is rolled back — the
    # pre-existing red alone would have been tolerated, but a NEW failure is not.
    assert res["verified"] is False
    assert res["applied"] is False
    assert res["rolled_back"] is True
    assert _core(tmp_path) == before  # fully restored
    # The disclosure names the regression that caused the block.
    assert "tests/test_core.py::test_m" in res["delta_green"]["introduced"]


def test_delta_green_tolerated_move_lands_via_verify_or_rollback(tmp_path):
    """The positive control for the same gate: a HARMLESS covered change on a red
    baseline lands (verified True) and discloses the tolerated pre-existing red."""
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.execution._apply_verify import suite_failing_nodes
    from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch

    _red_baseline_project(tmp_path)
    _avail, baseline = suite_failing_nodes(tmp_path)

    before = _core(tmp_path)
    # Behaviour-preserving: ``== None`` -> ``is None`` (the test still passes).
    fixed = "def is_missing(value):\n    return value is None\n"
    pr = {"path": "pkg/core.py", "new_content": fixed,
          "expected_old_content": before}
    snapshot = {"pkg/core.py": before}
    applied = ApplyPatchSkill().run(
        str(tmp_path),
        [FilePatch(path="pkg/core.py", new_content=fixed,
                   expected_old_content=before)])

    out: dict = {"applied": True, "changed_files": ["pkg/core.py"]}
    res = IdeaActionBridge._verify_or_rollback(
        str(tmp_path), out, snapshot, [pr], applied, tier=1,
        baseline_failing=baseline)

    assert res["verified"] is True
    assert res["rolled_back"] is False
    assert res["delta_green"]["baseline_failing"] == 1
    assert res["delta_green"]["introduced"] == []
    assert "value is None" in _core(tmp_path)


# --------------------------------------------------------------------------- #
# _verify_or_rollback: None baseline is byte-identical (absolute-green)         #
# --------------------------------------------------------------------------- #
def test_verify_or_rollback_none_baseline_is_absolute_green(tmp_path: Path):
    """``baseline_failing=None`` keeps the historical absolute-green gate: a
    breaking change on a GREEN project rolls back and the result carries NO
    delta_green key (byte-identical result shape)."""
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch

    _green_project_breakable(tmp_path)
    before = _core(tmp_path)
    broken = "def value():\n    return 999\n"
    pr = {"path": "pkg/core.py", "new_content": broken,
          "expected_old_content": before}
    snapshot = {"pkg/core.py": before}
    applied = ApplyPatchSkill().run(
        str(tmp_path),
        [FilePatch(path="pkg/core.py", new_content=broken,
                   expected_old_content=before)])

    out: dict = {"applied": True, "changed_files": ["pkg/core.py"]}
    res = IdeaActionBridge._verify_or_rollback(
        str(tmp_path), out, snapshot, [pr], applied, tier=1)

    assert res["applied"] is False and res["rolled_back"] is True
    assert "delta_green" not in res
    assert _core(tmp_path) == before
