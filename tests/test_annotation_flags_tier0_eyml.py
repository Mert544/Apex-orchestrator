"""Pure-ANNOTATION security flags are Tier-0 (no coverage gate for a comment).

Red-team finding (microservice fuzz): the comment-only security flags
``flag_tls_verify`` / ``flag_pickle_loads`` / ``flag_sql_injection`` were tiered
behaviour-adjacent (Tier-1) because they route through the ``harden_security``
action. On an UNTESTED module that meant the top TLS-off finding was neither
applied nor surfaced — and worse, the test-first shield spun up a network-calling
contract test that failed and rolled the comment back.

But these transforms insert exactly ONE ``# SECURITY (...)`` comment above the
call site and leave the dangerous call byte-for-byte intact: the runnable AST is
unchanged, so the fix cannot need a covering test. They are Tier-0 by the same
rule as a docstring or a new test file.

HARD GATES pinned here:
  * A pure-annotation flag is Tier-0: it applies on an untested module with NO
    shield/coverage gate, is not rolled back for lack of a test, and no
    network-calling shield test is generated for it.
  * A behaviour-CHANGING harden (eval -> literal_eval, yaml.load -> safe_load)
    STAYS Tier-1 and keeps its coverage gate — the moat fix is not loosened.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _MaintenancePass
from app.execution.risk_tiers import (
    ANNOTATION_FLAG_TRANSFORMS,
    tier_for,
    tier_for_transform,
)
from app.models.idea import ActionPlan, ActionStep


# --- Unit pins: the tier-of-a-transform classifier ---------------------------

def test_annotation_flag_transforms_are_tier0():
    # The three comment-only flags are Tier-0 regardless of the carrying action.
    for transform in ("flag_tls_verify", "flag_pickle_loads", "flag_sql_injection"):
        assert transform in ANNOTATION_FLAG_TRANSFORMS
        assert tier_for_transform(transform, "harden_security") == 0


def test_behaviour_changing_harden_stays_tier1():
    # A real rewrite carries no annotation transform_type -> it falls back to the
    # harden action's tier, which STAYS Tier-1 (coverage gate intact).
    assert tier_for("harden_security") == 1
    assert tier_for_transform("yaml_load_to_safe_load", "harden_security") == 1
    assert tier_for_transform("literal_eval_rewrite", "harden_security") == 1
    # An unresolved/None transform on a harden step is conservatively Tier-1.
    assert tier_for_transform(None, "harden_security") == 1


def test_tier_for_transform_preserves_non_harden_tiers():
    # The helper never *lowers* a Tier-0 action and never raises a Tier-2 one.
    assert tier_for_transform("add_ci_workflow", "add_ci") == 0
    assert tier_for_transform("design_note", "design_task") == 2


# --- Integration helpers -----------------------------------------------------

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


def _run(root: Path, step: ActionStep, *, mode: str, commit: bool) -> dict:
    plan = ActionPlan(steps=[step], mode=mode)
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode=mode, verify=True, commit=commit,
        test_first=True, max_apply=3,
    )


# --- PIN 1: TLS-off flag on an UNTESTED module -> applied, Tier-0, no shield --

def test_tls_flag_applies_on_untested_module_without_coverage_gate(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # An HTTP client with TLS verification disabled, in a module NO test
    # references. The fix is a comment-only flag (verify=False is left intact).
    src = tmp_path / "app" / "client.py"
    src.write_text(
        "import requests\n"
        "def fetch(u):\n"
        "    return requests.get(u, verify=False)\n"
    )
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")

    summary = _run(tmp_path, _harden_step("app/client.py"),
                   mode="supervised", commit=False)

    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]
    # Applied, NOT blocked, NOT rolled back — no covering test was demanded.
    assert row["applied"] is True
    assert row.get("rolled_back") is not True
    assert row["transform_type"] == "flag_tls_verify"
    # Tier-0: the comment-only flag is priced as additive.
    assert row["risk_tier"] == 0
    # NO network-calling shield test was generated for it (the bug was that the
    # shield spun one up and rolled the comment back).
    assert "shield_test" not in row
    # The comment is inserted and the dangerous call is preserved byte-for-byte.
    after = src.read_text()
    assert "# SECURITY (Apex: TLS verification" in after
    assert "requests.get(u, verify=False)" in after


def test_tls_flag_not_blocked_in_summary_counters(tmp_path):
    # Same scenario from the summary's vantage: the flag lands in `applied`,
    # never in `blocked` (the red-team's "neither applied nor surfaced" path).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "client.py"
    src.write_text(
        "import requests\n"
        "def fetch(u):\n"
        "    return requests.get(u, verify=False)\n"
    )
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")

    summary = _run(tmp_path, _harden_step("app/client.py"),
                   mode="supervised", commit=False)

    assert summary["applied"] >= 1
    assert summary["blocked"] == 0


# --- PIN 2: pickle/sql flags are Tier-0 too ----------------------------------

def test_pickle_and_sql_flags_are_tier0_on_untested_modules(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "ser.py").write_text(
        "import pickle\ndef load(b):\n    return pickle.loads(b)\n")
    (tmp_path / "app" / "db.py").write_text(
        'def get(cur, uid):\n'
        '    return cur.execute(f"SELECT * FROM u WHERE id={uid}")\n')
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")

    for target, transform in (("app/ser.py", "flag_pickle_loads"),
                              ("app/db.py", "flag_sql_injection")):
        summary = _run(tmp_path, _harden_step(target),
                       mode="supervised", commit=False)
        rows = [r for r in summary["results"] if r["action"] == "harden_security"]
        assert len(rows) == 1
        row = rows[0]
        assert row["applied"] is True
        assert row["transform_type"] == transform
        assert row["risk_tier"] == 0
        assert "shield_test" not in row


# --- PIN 3: a comment-only flag commits at coverage "none" (Tier-0) ----------

def test_tls_flag_autocommits_with_no_coverage(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "client.py"
    src.write_text(
        "import requests\n"
        "def fetch(u):\n"
        "    return requests.get(u, verify=False)\n"
    )
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git_init(tmp_path)

    summary = _run(tmp_path, _harden_step("app/client.py"),
                   mode="autonomous", commit=True)

    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]
    assert row["applied"] is True
    assert row["risk_tier"] == 0
    # Tier-0 commits regardless of coverage — the unverified-behaviour-change
    # gate never fires for a comment-only flag.
    assert row["committed"] is True
    assert row.get("commit_withheld") is not True
    assert _MaintenancePass._unverified_behaviour_change(row, 0) is False


# --- HARD GATE: a behaviour-CHANGING harden STAYS Tier-1 (gate intact) -------

def test_yaml_rewrite_stays_tier1_with_coverage_gate(tmp_path):
    # yaml.load -> safe_load is a real behaviour change. On an untested module
    # the only coverage is the smoke-import shield, so it must report Tier-1,
    # verified=False, and be WITHHELD from auto-commit — the moat fix the
    # red-team relied on must NOT be loosened by moving the comment flags.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    cfg = tmp_path / "app" / "cfg.py"
    cfg.write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git_init(tmp_path)

    summary = _run(tmp_path, _harden_step("app/cfg.py"),
                   mode="autonomous", commit=True)

    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]
    assert "yaml.safe_load" in cfg.read_text()      # applied on disk
    assert row["risk_tier"] >= 1                     # STAYS behaviour-adjacent
    assert row["verified"] is False                  # only smoke-shield coverage
    assert row["coverage"] in ("none", "module")
    assert row["committed"] is False                 # gate withholds the commit
    assert row["commit_withheld"] is True
