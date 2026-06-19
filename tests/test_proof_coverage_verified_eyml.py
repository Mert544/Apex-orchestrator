"""``verified`` must be coverage- AND tier-aware — a green suite only verifies a
change it actually exercised, never one it never looked at.

A red-team audit reproduced a "fake green": a behaviour-adjacent fix
(``eval`` → ``ast.literal_eval``, ``== None`` → ``is None``) applied on a module
no test references was reported ``verified: True`` while the verification
strength was ``none`` — a self-contradicting proof record. The fix makes
``verified`` require coverage appropriate to the risk tier:

  * Tier 0 (semantics-preserving/additive): a test that imports the module
    (``module``) or names the change (``function``) suffices;
  * Tier 1+ (behaviour-adjacent): require ``function`` — a smoke import is not a
    test of the changed behaviour;
  * ``none`` never verifies anything.

The change is still KEPT on a green suite (the apply/rollback policy is
unchanged); only the honesty of ``verified`` is fixed. Deterministic.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import ActionStep


def _coverage_verifies(tier: int, coverage: str) -> bool:
    return IdeaActionBridge._coverage_verifies(tier, coverage)


# --- the pure tier/coverage rule -------------------------------------------

def test_coverage_rule_tier0():
    assert _coverage_verifies(0, "function") is True
    assert _coverage_verifies(0, "module") is True
    assert _coverage_verifies(0, "test-change") is True
    assert _coverage_verifies(0, "none") is False


def test_coverage_rule_tier1_requires_function():
    # A behaviour-adjacent change needs a test that NAMES the change; a mere
    # import (module-level, e.g. a smoke-import shield) is not enough.
    assert _coverage_verifies(1, "function") is True
    assert _coverage_verifies(1, "module") is False
    assert _coverage_verifies(1, "none") is False
    assert _coverage_verifies(1, "test-change") is True


# --- end-to-end: the reproduced contradiction is gone ----------------------

def _proj(tmp_path: Path, body: str) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(body, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_unrelated.py").write_text(
        "def test_t():\n    assert True\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return tmp_path


def test_blind_apply_is_kept_but_not_verified(tmp_path: Path):
    # Tier-0 modernize on a module no test references: kept (suite green) but
    # honestly NOT verified — no contradiction between verified and coverage.
    _proj(tmp_path, "def foo(x):\n    if x == None:\n        return 1\n    return 2\n")
    step = ActionStep(branch_path="x.0", title="t", operator="simplify",
                      subject="pkg/m.py", action_type="modernize_comparisons",
                      target="pkg/m.py", executable=True)
    out = IdeaActionBridge().apply_step(step, str(tmp_path),
                                        mode="supervised", run_tests=True, verify=True)
    assert out["applied"] is True
    assert out["suite_green"] is True
    assert out["coverage"] == "none"
    assert out["verified"] is False           # no longer the old fake green
    # the contradiction the audit found (verified True with strength none) is gone
    assert not (out["verified"] and out["coverage"] == "none")


def test_covered_change_is_verified(tmp_path: Path):
    # Same change, but now a test actually NAMES the changed function -> a
    # green suite genuinely verifies it.
    _proj(tmp_path, "def foo(x):\n    if x == None:\n        return 1\n    return 2\n")
    (tmp_path / "tests" / "test_real.py").write_text(
        "from pkg.m import foo\ndef test_foo():\n    assert foo(1) == 2\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="simplify",
                      subject="pkg/m.py", action_type="modernize_comparisons",
                      target="pkg/m.py", executable=True)
    out = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        run_tests=True, verify=True)
    assert out["applied"] is True
    assert out["coverage"] == "function"
    assert out["verified"] is True
