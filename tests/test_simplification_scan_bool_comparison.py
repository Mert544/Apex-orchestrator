"""The newly-wired ``bool-comparison`` simplification must be discoverable by
the scanner and executable end-to-end through the bridge.

These assert the discovery end (the scanner emits the EXACT ``bool-comparison``
fact-label the bridge's ``_FACT_ACTIONS`` expects, only when the on-disk
``plan_simplify_bool_comparison`` transform would actually fire, and the scan is
a deterministic, pure superset) and the apply end (a matching module is rewritten
through the same guarded gate; a negative sample fabricates nothing).

Deterministic: fixed sources, no time/random.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.models.idea import ActionStep
from app.tools.simplification_scan import _transforms, scan_simplifications

# A module whose ONLY simplifiable shape is a provably-bool comparison against a
# bool literal: ``(a < b) == True`` -> ``(a < b)``. The operand is a ``Compare``,
# so the rewrite is value-preserving.
_MATCH = "def f(a, b):\n    return (a < b) == True\n"
# Nothing to simplify (and the bare-name ``x == True`` below is provably-unsound,
# so it must NOT be flagged either).
_CLEAN = "def f(x):\n    return x\n"
_BARE = "def f(x):\n    return x == True\n"


def _step(target: str) -> ActionStep:
    return ActionStep(
        branch_path="x.0",
        title="t",
        operator="root",
        subject=target,
        action_type="simplify_bool_comparison",
        target=target,
        executable=True,
    )


def test_bool_comparison_is_in_the_scan_table() -> None:
    """The scanner advertises the ``bool-comparison`` fact, and it routes to the
    executable ``simplify_bool_comparison`` action in the bridge."""
    labels = {label for label, _apply in _transforms()}
    assert "bool-comparison" in labels
    action, _desc, executable = _FACT_ACTIONS["bool-comparison"]
    assert action == "simplify_bool_comparison"
    assert executable is True


def test_scan_detects_the_match(tmp_path: Path) -> None:
    """A module with a provably-bool comparison yields exactly the
    ``bool-comparison`` opportunity (the fact-label the bridge expects)."""
    (tmp_path / "mod.py").write_text(_MATCH, encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    bc = [o for o in opps if o["fact_label"] == "bool-comparison"]
    assert len(bc) == 1
    assert bc[0]["module"] == "mod.py"
    assert bc[0]["transform"] == "bool_comparison"


def test_scan_skips_clean_and_unsound(tmp_path: Path) -> None:
    """No opportunity on a clean module, and — critically — none on the
    provably-UNSOUND bare-name ``x == True`` (the scan fabricates nothing)."""
    (tmp_path / "clean.py").write_text(_CLEAN, encoding="utf-8")
    (tmp_path / "bare.py").write_text(_BARE, encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    assert not [o for o in opps if o["fact_label"] == "bool-comparison"]


def test_scan_is_deterministic(tmp_path: Path) -> None:
    """Same tree in -> same opportunity list out (pure, no time/random)."""
    (tmp_path / "mod.py").write_text(_MATCH, encoding="utf-8")
    assert scan_simplifications(tmp_path) == scan_simplifications(tmp_path)


def test_apply_rewrites_match_through_guarded_gate(tmp_path: Path) -> None:
    """The discovered opportunity is genuinely executable: an autonomous
    apply_step rewrites the module via the same snapshot/apply gate."""
    import ast

    bridge = IdeaActionBridge()
    rel = "mod.py"
    (tmp_path / rel).write_text(_MATCH, encoding="utf-8")
    out = bridge.apply_step(_step(rel), str(tmp_path), mode="autonomous")
    assert out["applied"] is True
    assert out["transform_type"] == "simplify-bool-comparison"
    written = (tmp_path / rel).read_text(encoding="utf-8")
    assert written != _MATCH
    assert "== True" not in written  # the redundant comparison is gone
    ast.parse(written)


def test_apply_keeps_on_green(tmp_path: Path) -> None:
    """With verify on and a green suite, a behaviour-preserving rewrite is KEPT
    (snapshot -> write -> test-verify passes, no rollback)."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    rel = "mod.py"
    (tmp_path / rel).write_text(_MATCH, encoding="utf-8")
    bridge = IdeaActionBridge()
    out = bridge.apply_step(_step(rel), str(tmp_path),
                            mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is True
    assert out.get("rolled_back") is False
    assert out.get("verified") is True
    assert (tmp_path / rel).read_text(encoding="utf-8") != _MATCH


def test_apply_rolls_back_on_red(tmp_path: Path) -> None:
    """With verify on and a red suite, the change is rolled back byte-for-byte —
    the auto-rollback gate is not weakened for this transform."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_red.py").write_text(
        "def test_red():\n    assert False\n", encoding="utf-8")
    rel = "mod.py"
    (tmp_path / rel).write_text(_MATCH, encoding="utf-8")
    bridge = IdeaActionBridge()
    out = bridge.apply_step(_step(rel), str(tmp_path),
                            mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is False
    assert out.get("rolled_back") is True
    assert (tmp_path / rel).read_text(encoding="utf-8") == _MATCH


def test_negative_sample_fabricates_nothing(tmp_path: Path) -> None:
    """A clean module produces no patch and is never written."""
    bridge = IdeaActionBridge()
    rel = "clean.py"
    (tmp_path / rel).write_text(_CLEAN, encoding="utf-8")
    result = bridge._generate(_step(rel), str(tmp_path))
    assert result is None
    out = bridge.apply_step(_step(rel), str(tmp_path), mode="autonomous")
    assert out["applied"] is False
    assert (tmp_path / rel).read_text(encoding="utf-8") == _CLEAN
