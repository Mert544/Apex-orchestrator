"""BASELINE-RED honesty — a fix verified against an ALREADY-failing suite is
inconclusive, not verified, and must be withheld from auto-commit.

Per-fix verification runs the suite AFTER applying a fix and treats green as
proof the fix is safe. But if the suite was already RED *before* Apex touched
anything, a green-after (or a still-red that merely didn't worsen) cannot be
attributed to the fix — yet the proof/verification path used to record
verification strength as if it were earned. This closes that gap.

The fix is a ONE-TIME baseline pre-flight on the maintenance pass: before the
first apply, run the verification command ONCE and cache ``baseline_green``
(never re-run per step). When ``baseline_green is False`` every applied fix's
verification is downgraded to the weakest tier ``baseline-red``,
``verified=False``, and the autonomous-commit gate WITHHOLDS the commit with a
clear reason; the proof artifact records ``baseline_green=False``. When
``baseline_green is True`` (the common case) behaviour and proofs are
BYTE-IDENTICAL to today — the pre-flight simply confirms green, with no
downgrade and no extra per-step suite runs.

HARD GATES pinned here:
  * Red baseline -> applied fix recorded ``baseline-red`` / ``verified=False``,
    NOT committed, ``commit_withheld``/``baseline_red`` flagged, reason explains
    the suite was already failing; the proof carries ``baseline_green=False``.
  * Green baseline -> the SAME fix verifies + commits exactly as before; its
    result + proof carry NO ``baseline_green`` key (byte-identical), and the
    suite is NOT double-run per step (one pre-flight, cached).
  * Determinism: two runs of the red-baseline pass produce identical rows.
  * The downgrade composes with (does not regress) the tier-1 / fence withholds.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _MaintenancePass
from app.engine.proof_of_fix import build_proof, proof_manifest
from app.models.idea import ActionPlan, ActionStep


# --- helpers -----------------------------------------------------------------

def _git_init(root: Path) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=root, capture_output=True)


def _harden_step(target: str, branch: str = "x.1") -> ActionStep:
    # ``yaml.load(s)`` -> ``yaml.safe_load(s)`` is a Tier-1 harden the function
    # test NAMES (coverage "function"). On a GREEN baseline this verifies and
    # commits exactly as today; on a RED baseline the post-apply green cannot be
    # attributed to the fix, so it is downgraded to ``baseline-red``.
    return ActionStep(
        branch_path=branch, title=f"harden {target}", operator="harden",
        subject=target, action_type="harden_security", target=target,
        executable=True, source_facts=[f"security-finding: {target}"],
    )


def _run(root: Path, steps: list[ActionStep], *, mode: str = "autonomous",
         commit: bool = True) -> dict:
    plan = ActionPlan(steps=steps, mode=mode)
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode=mode, verify=True, commit=commit,
        test_first=True, max_apply=5,
    )


def _committed(root: Path, rel: str) -> bool:
    """True when ``rel``'s change is committed (working tree clean for it)."""
    out = subprocess.run(["git", "status", "--short", rel],
                         cwd=root, capture_output=True, text=True).stdout
    return rel not in out


# A module with a Tier-1 fixable vuln (bare ``yaml.load``). A function test
# NAMES ``load`` (coverage "function").
_CFG_SRC = "import yaml\ndef load(s):\n    return yaml.load(s)\n"
_CFG_TEST = ('from app.cfg import load\n'
             'def test_load():\n    assert load("a: 1") == {"a": 1}\n')


def _build_red(root: Path) -> None:
    """RED baseline: the function test calls ``yaml.load(s)`` which RAISES
    "missing Loader" before the fix, so the suite is ALREADY failing. The
    ``yaml.load`` -> ``yaml.safe_load`` harden then turns it green — but that
    green-after cannot be attributed to the fix, so it is inconclusive."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "cfg.py").write_text(_CFG_SRC)
    (root / "tests" / "test_cfg.py").write_text(_CFG_TEST)
    _git_init(root)


def _build_green(root: Path) -> None:
    """GREEN baseline (the common case): a Tier-1 ``eval`` -> ``ast.literal_eval``
    harden whose behaviour the rewrite PRESERVES, so the function test passes
    BOTH before and after — the suite is green before Apex touches anything. The
    fix verifies (coverage "function") and commits exactly as today."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "cfg.py").write_text(
        "def load(s):\n    return eval(s)\n")
    (root / "tests" / "test_cfg.py").write_text(
        'from app.cfg import load\n'
        'def test_load():\n    assert load("{\'a\': 1}") == {"a": 1}\n')
    _git_init(root)


# --- PIN 1: red baseline -> inconclusive, withheld, proof says so ------------

def test_red_baseline_fix_is_baseline_red_not_committed(tmp_path):
    _build_red(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])

    row = next(r for r in summary["results"]
               if r["action"] == "harden_security")

    # The fix IS applied on disk (left for review) and the post-apply suite is
    # GREEN — but that green cannot be attributed to the fix (red baseline)...
    assert row["applied"] is True
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()
    assert row.get("suite_green") is True            # the dangerous "fake green"

    # ...so its verification is INCONCLUSIVE: the suite was already red.
    assert row["verified"] is False
    assert row["coverage"] == "baseline-red"
    assert row["verification_strength"]["level"] == "baseline-red"
    assert row["baseline_green"] is False

    # ...so it is NOT auto-committed, and the row says why.
    assert row["committed"] is False
    assert row["commit_withheld"] is True
    assert row["baseline_red"] is True
    assert "already failing" in row["reason"]
    assert "review manually" in row["reason"]
    assert _committed(tmp_path, "app/cfg.py") is False
    assert summary["committed"] == 0


def test_red_baseline_proof_carries_baseline_green_false(tmp_path):
    _build_red(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])

    proof = build_proof(summary, str(tmp_path))
    fix = next(f for f in proof["fixes"]
               if f["finding"]["action"] == "harden_security")
    assert fix["outcome"] == "applied"
    assert fix["verification"]["baseline_green"] is False
    assert fix["verification"]["strength"]["level"] == "baseline-red"

    # The manifest tallies the inconclusive fix honestly under ``baseline-red``,
    # not silently collapsed into ``none``.
    manifest = proof_manifest(proof)
    assert manifest["by_coverage"]["baseline-red"] == 1
    assert manifest["by_coverage"]["none"] == 0


# --- PIN 2: green baseline -> byte-identical, verified, committed, no double-run

def test_green_baseline_commits_and_proof_is_byte_identical(tmp_path):
    _build_green(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])

    row = next(r for r in summary["results"]
               if r["action"] == "harden_security")

    # A green-baseline Tier-1 fix the function test names verifies + commits as
    # before — the pre-flight only confirmed green; it did not downgrade.
    assert row["applied"] is True
    assert row["committed"] is True
    assert row["verified"] is True
    assert row["coverage"] == "function"
    # No baseline-red contamination on the common path.
    assert "baseline_green" not in row
    assert "baseline_red" not in row
    assert row.get("coverage") != "baseline-red"
    assert _committed(tmp_path, "app/cfg.py") is True

    # The proof carries NO ``baseline_green`` key on the green path (additive
    # field present only when the baseline was red) -> byte-identical to before.
    proof = build_proof(summary, str(tmp_path))
    fix = next(f for f in proof["fixes"]
               if f["finding"]["action"] == "harden_security")
    assert "baseline_green" not in fix["verification"]
    manifest = proof_manifest(proof)
    assert "baseline-red" not in manifest["by_coverage"]


def test_green_baseline_does_not_double_run_the_suite(tmp_path, monkeypatch):
    _build_green(tmp_path)

    # Count every full-suite invocation across the whole pass.
    from app.skills.execution.run_tests import RunTestsSkill

    calls: list[str] = []
    original = RunTestsSkill.run

    def _counting_run(self, project_root, commands=None):
        calls.append(str(project_root))
        return original(self, project_root, commands)

    monkeypatch.setattr(RunTestsSkill, "run", _counting_run)

    # Three fix steps on the SAME target -> one pre-flight for the whole pass,
    # then a per-step verify only while the fix still lands (the eval rewrite is
    # idempotent, so later steps are no-ops that never reach verify).
    _run(tmp_path, [_harden_step("app/cfg.py", "x.1"),
                    _harden_step("app/cfg.py", "x.2"),
                    _harden_step("app/cfg.py", "x.3")])

    # The pre-flight runs the suite ONCE for the whole pass (cached), NOT once
    # per step. If the pre-flight re-ran per step it would add one extra run per
    # step (>= 3 here) — so a tight bound FAILS the double-run regression while
    # passing the cached single pre-flight (1 pre-flight + the first step's
    # verify + a possible shield run).
    assert len(calls) <= 4, f"pre-flight double-ran: {len(calls)} suite runs"


# --- PIN 3: the cached baseline is a deterministic bool ----------------------

def test_baseline_preflight_is_cached_bool(tmp_path):
    _build_green(tmp_path)
    bridge = IdeaActionBridge()
    run = _MaintenancePass(bridge, str(tmp_path), mode="autonomous",
                           verify=True, test_first=True, commit=False)
    assert run._baseline_green is None              # not probed yet
    first = run._ensure_baseline()
    assert first is True                            # green fixture
    assert run._baseline_green is True
    # Cached: a second call returns the same bool without re-probing.
    assert run._ensure_baseline() is True

    red = tmp_path / "red"
    _build_red(red)
    run_red = _MaintenancePass(bridge, str(red), mode="autonomous",
                               verify=True, test_first=True, commit=False)
    assert run_red._ensure_baseline() is False
    assert run_red._baseline_green is False


def test_red_baseline_pass_is_deterministic(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _build_red(root_a)
    _build_red(root_b)
    a = _run(root_a, [_harden_step("app/cfg.py")])
    b = _run(root_b, [_harden_step("app/cfg.py")])

    nondet = {"commit_hash", "duration_seconds"}

    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in sorted(obj.items())
                    if k not in nondet}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    assert strip(a["results"]) == strip(b["results"])


# --- PIN 4: the downgrade composes with the tier-1 withhold (no regression) --

def test_baseline_red_does_not_break_tier1_withhold_semantics(tmp_path):
    # A red baseline still leaves the fix applied-on-disk for review (the tier-1
    # withhold's "apply but don't commit" contract is preserved, just for a
    # different reason) and never reverts the hunk.
    _build_red(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    row = next(r for r in summary["results"]
               if r["action"] == "harden_security")
    assert row["applied"] is True                   # applied, NOT rolled back
    assert row.get("rolled_back") is not True
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()
    assert row["committed"] is False
