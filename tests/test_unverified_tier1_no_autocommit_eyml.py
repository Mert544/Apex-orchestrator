"""Autonomous mode must never auto-COMMIT an unverified behaviour change.

A Tier-1 (behaviour-adjacent) harden — ``eval`` → ``literal_eval``,
``yaml.load`` → ``yaml.safe_load`` — whose ONLY coverage is the test-first
smoke-import shield (which imports the module but never calls the changed
function) reports ``verified=False`` / ``coverage="module"``. The fix is fine
to APPLY on disk, but a buyer must never get it silently auto-committed.

These pins exercise the gate in ``_MaintenancePass._settle_applied``:

  - Tier-1 + smoke-shield-only -> APPLIED on disk, NOT committed, report says so.
  - Tier-1 + a REAL function-level test -> verified, committed as today.
  - Tier-0 modernization (semantics-preserving) -> committed even at coverage
    "none" (it changes no behaviour).
  - Supervised mode is UNCHANGED: it still applies the same Tier-1 step (the
    gate only touches the autonomous auto-commit path).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import ActionPlan, ActionStep


def _git_init(root: Path) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=root, capture_output=True)


def _harden_step(target: str) -> ActionStep:
    return ActionStep(
        branch_path="x.1", title=f"harden {target}", operator="harden",
        subject=target, action_type="harden_security", target=target,
        executable=True, source_facts=[f"security-finding: {target}"],
    )


def _run(root: Path, step: ActionStep, *, mode: str, test_first: bool) -> dict:
    plan = ActionPlan(steps=[step], mode=mode)
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode=mode, verify=True, commit=True,
        test_first=test_first, max_apply=3,
    )


def _committed_cfg(root: Path) -> bool:
    """True when the working tree's cfg.py change has been committed (clean)."""
    out = subprocess.run(["git", "status", "--short", "app/cfg.py"],
                         cwd=root, capture_output=True, text=True).stdout
    return "app/cfg.py" not in out


# --- PIN 1: smoke-shield-only Tier-1 harden -> applied, NOT committed --------

def test_autonomous_withholds_commit_for_smoke_shield_only_tier1(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # yaml.load -> Tier-1 harden. Suite is green but the only test that could
    # cover cfg.py is the smoke-import shield Apex itself writes (module-level).
    (tmp_path / "app" / "cfg.py").write_text(
        "import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git_init(tmp_path)

    summary = _run(tmp_path, _harden_step("app/cfg.py"),
                   mode="autonomous", test_first=True)

    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]
    # The fix IS applied on disk...
    assert row["applied"] is True
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()
    # ...but it is an unverified behaviour change: coverage is only module-level
    # (the smoke shield), verified is False, so it must NOT be committed.
    assert row["risk_tier"] >= 1
    assert row["verified"] is False
    assert row["coverage"] in ("none", "module")
    assert row["committed"] is False
    assert row["commit_withheld"] is True
    assert "NOT committed" in row["reason"]
    assert "review before committing" in row["reason"]
    # The behaviour change is genuinely uncommitted in git (only the additive
    # shield test, a Tier-0 commit, may have landed).
    assert _committed_cfg(tmp_path) is False


# --- PIN 2: a REAL function-level test -> committed as today -----------------

def test_autonomous_commits_tier1_with_real_function_test(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # ``eval`` -> ``ast.literal_eval`` is a Tier-1 harden whose behaviour the
    # rewrite PRESERVES, so the test that calls load() passes BOTH before and
    # after — i.e. the baseline is genuinely GREEN. (A ``yaml.load(s)`` fixture
    # would raise "missing Loader" at the pre-fix baseline, making the baseline
    # RED — exactly the inconclusive case test_baseline_red_eyml pins — so it is
    # the wrong fixture for the verified-and-committed green-baseline path.)
    (tmp_path / "app" / "cfg.py").write_text(
        "def load(s):\n    return eval(s)\n")
    # A real function-level test: imports cfg AND calls load() -> coverage
    # "function", verified True after the literal_eval rewrite.
    (tmp_path / "tests" / "test_cfg.py").write_text(
        'from app.cfg import load\n'
        'def test_load():\n    assert load("{\'a\': 1}") == {"a": 1}\n')
    _git_init(tmp_path)

    summary = _run(tmp_path, _harden_step("app/cfg.py"),
                   mode="autonomous", test_first=True)

    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]
    assert row["applied"] is True
    assert row["verified"] is True
    assert row["coverage"] == "function"
    assert row["committed"] is True
    assert "commit_hash" in row
    assert row.get("commit_withheld") is not True
    # The behaviour change is committed -> working tree is clean for cfg.py.
    assert _committed_cfg(tmp_path) is True
    assert summary["committed"] >= 1


# --- PIN 3: Tier-0 modernization commits even at coverage "none" -------------

def test_autonomous_commits_tier0_modernization_with_no_coverage(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # `== None` -> `is None` is semantics-preserving (Tier 0); it changes no
    # behaviour, so it commits even though NO test references the module.
    (tmp_path / "app" / "mod.py").write_text(
        "def chk(x):\n    if x == None:\n        return 1\n    return 0\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git_init(tmp_path)

    step = ActionStep(
        branch_path="x.1", title="modernize app/mod.py", operator="simplify",
        subject="app/mod.py", action_type="modernize_comparisons",
        target="app/mod.py", executable=True,
        source_facts=["modernization: app/mod.py"],
    )
    # test_first off so the modernization's coverage stays honestly "none".
    summary = _run(tmp_path, step, mode="autonomous", test_first=False)

    rows = [r for r in summary["results"] if r["action"] == "modernize_comparisons"]
    assert len(rows) == 1
    row = rows[0]
    assert row["applied"] is True
    assert row["risk_tier"] == 0
    assert row["coverage"] == "none"
    # Tier-0 commits regardless of coverage — the gate never fires for it.
    assert row["committed"] is True
    assert row.get("commit_withheld") is not True
    assert "is None" in (tmp_path / "app" / "mod.py").read_text()


# --- HARD GATE: supervised mode is unchanged (still applies the step) --------

def test_supervised_mode_still_applies_the_tier1_step_unchanged(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text(
        "import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    # No git repo needed: supervised never commits.

    summary = _run(tmp_path, _harden_step("app/cfg.py"),
                   mode="supervised", test_first=True)

    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]
    # Same apply outcome as before the gate: applied on disk, nothing committed
    # (supervised has no committer), and the gate did NOT mark it withheld.
    assert row["applied"] is True
    assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()
    assert summary["committed"] == 0
    assert row.get("commit_withheld") is not True


# --- Helper-level pin: the gate predicate itself ----------------------------

def test_unverified_behaviour_change_predicate():
    from app.engine.idea_action_bridge import _MaintenancePass

    pred = _MaintenancePass._unverified_behaviour_change
    # Tier-1, smoke-shield-only -> withhold.
    assert pred({"verified": False, "coverage": "module"}, 1) is True
    assert pred({"verified": False, "coverage": "none"}, 1) is True
    # Tier-1, real function test -> commit.
    assert pred({"verified": True, "coverage": "function"}, 1) is False
    # Tier-0 -> never withheld, even at coverage none.
    assert pred({"verified": False, "coverage": "none"}, 0) is False
    # Missing coverage key is treated as no coverage (conservative).
    assert pred({"verified": False}, 1) is True
