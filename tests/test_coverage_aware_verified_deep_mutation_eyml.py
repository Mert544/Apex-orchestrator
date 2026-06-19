"""Deep mutation-hardening for the proof-integrity wave's coverage-aware verdict.

Two moat-critical rules added this session must resist single-token mutation:

1. ``IdeaActionBridge._coverage_verifies(tier, coverage)`` — the EXACT truth
   table that decides whether a green suite genuinely vouches for a change:
     * ``test-change`` always verifies (the changed files ARE the suite);
     * Tier 0 (semantics-preserving) needs ``module`` OR ``function`` coverage;
     * Tier 1+ (behaviour-adjacent) needs ``function`` — a mere import shield
       (``module``) must NEVER green-light it;
     * ``none`` never verifies anything.
   A flipped comparison (``tier <= 0`` -> ``tier < 0`` / ``>= 0``), a swapped
   tier threshold, or a dropped membership branch all change at least one cell
   below, so each is killed.

2. ``IdeaActionBridge._partial_or_noop_block`` — a PARTIAL multi-file apply
   (some patches skipped on an ``expected_old_content`` mismatch) and a NO-OP
   apply (written content equals what was already on disk) must both report
   ``applied=False`` and RESTORE every file we did write. These are the two
   write outcomes that must not masquerade as a fix.

Determinism: every assertion is exact-value (booleans, dict fields, on-disk
file text); no timestamps, wall-clock, or set/dict iteration order.
"""
from __future__ import annotations

from app.engine.idea_action_bridge import IdeaActionBridge
from app.skills.execution.apply_patch import PatchApplyResult

_COVERAGE_VERIFIES = IdeaActionBridge._coverage_verifies


# ---------------------------------------------------------------------------
# _coverage_verifies — the full truth table, one cell per assertion so a single
# flipped comparison / swapped threshold / dropped branch is killed exactly.
# Tiers spanned: the boundary 0 and a representative 1 and a high tier.
# Coverage levels: the four producible by assess_strength.
# ---------------------------------------------------------------------------
def test_test_change_always_verifies_regardless_of_tier():
    # The changed files ARE the suite: every tier verifies on test-change.
    assert _COVERAGE_VERIFIES(0, "test-change") is True
    assert _COVERAGE_VERIFIES(1, "test-change") is True
    assert _COVERAGE_VERIFIES(2, "test-change") is True
    assert _COVERAGE_VERIFIES(99, "test-change") is True


def test_tier0_function_coverage_verifies():
    assert _COVERAGE_VERIFIES(0, "function") is True


def test_tier0_module_coverage_verifies():
    # The Tier-0 leniency: a smoke-import shield DOES suffice for an
    # additive/semantics-preserving change.
    assert _COVERAGE_VERIFIES(0, "module") is True


def test_tier0_none_coverage_never_verifies():
    assert _COVERAGE_VERIFIES(0, "none") is False


def test_tier1_function_coverage_verifies():
    assert _COVERAGE_VERIFIES(1, "function") is True


def test_tier1_module_coverage_does_not_verify():
    # The behaviour the wave added: a mere import is NOT a test of behaviour at
    # Tier 1+. A mutant that lets ``module`` through here is killed.
    assert _COVERAGE_VERIFIES(1, "module") is False


def test_tier1_none_coverage_does_not_verify():
    assert _COVERAGE_VERIFIES(1, "none") is False


def test_high_tier_module_coverage_does_not_verify():
    # Any tier above the 0 boundary behaves like Tier 1 — module is too weak.
    assert _COVERAGE_VERIFIES(2, "module") is False
    assert _COVERAGE_VERIFIES(5, "module") is False


def test_high_tier_function_coverage_verifies():
    assert _COVERAGE_VERIFIES(2, "function") is True
    assert _COVERAGE_VERIFIES(5, "function") is True


def test_negative_tier_is_treated_as_tier0_leniency():
    # The guard is ``tier <= 0`` (NOT ``tier == 0`` / ``tier < 0``): a tier
    # below the boundary must keep the module-coverage leniency. A mutant that
    # turns ``<=`` into ``<`` would reject module here and is killed.
    assert _COVERAGE_VERIFIES(-1, "module") is True
    assert _COVERAGE_VERIFIES(-1, "function") is True
    assert _COVERAGE_VERIFIES(-1, "none") is False


def test_boundary_zero_keeps_module_leniency_but_one_does_not():
    # The exact threshold pin: tier 0 accepts module, tier 1 does not. A mutant
    # that shifts the threshold (``<= 0`` -> ``<= 1``) would make tier 1 accept
    # module and is killed by the pair.
    assert _COVERAGE_VERIFIES(0, "module") is True
    assert _COVERAGE_VERIFIES(1, "module") is False


def test_none_never_verifies_at_any_tier():
    for tier in (-1, 0, 1, 2, 7):
        assert _COVERAGE_VERIFIES(tier, "none") is False


def test_unknown_coverage_string_falls_through_to_function_rule():
    # An unrecognised coverage label is not ``function``/``module``/``test-change``,
    # so it must verify nowhere — the conservative default.
    assert _COVERAGE_VERIFIES(0, "weird") is False
    assert _COVERAGE_VERIFIES(1, "weird") is False


# ---------------------------------------------------------------------------
# _partial_or_noop_block — PARTIAL apply: a skipped file means a half-applied
# multi-file state, which must be blocked (applied=False) and rolled back.
# ---------------------------------------------------------------------------
def _bridge() -> IdeaActionBridge:
    return IdeaActionBridge()


def test_partial_apply_blocks_and_reports_reason(tmp_path):
    root = str(tmp_path)
    wrote = tmp_path / "good.py"
    wrote.write_text("written\n", encoding="utf-8")
    snapshot = {"good.py": "original\n", "bad.py": "orig-bad\n"}
    applied = PatchApplyResult(
        project_root=root,
        changed_files=["good.py"],
        skipped_files=["bad.py"],
        ok=True,
    )
    patch_requests = [
        {"path": "good.py", "new_content": "written\n"},
        {"path": "bad.py", "new_content": "wanted\n"},
    ]
    block = _bridge()._partial_or_noop_block(
        root, snapshot, applied, patch_requests, "merge_nested_if", "auto")

    assert block is not None
    assert block["applied"] is False
    assert block["reason"] == "partial apply (expected_old_content mismatch)"
    assert block["transform_type"] == "merge_nested_if"
    assert block["mode"] == "auto"
    assert block["skipped_files"] == ["bad.py"]


def test_partial_apply_restores_the_one_file_it_wrote(tmp_path):
    root = str(tmp_path)
    wrote = tmp_path / "good.py"
    wrote.write_text("written-half-state\n", encoding="utf-8")
    snapshot = {"good.py": "ORIGINAL-CONTENT\n"}
    applied = PatchApplyResult(
        project_root=root,
        changed_files=["good.py"],
        skipped_files=["bad.py"],
        ok=True,
    )
    patch_requests = [{"path": "good.py", "new_content": "written-half-state\n"}]
    _bridge()._partial_or_noop_block(
        root, snapshot, applied, patch_requests, "t", "auto")
    # The half-applied file must be restored to its snapshot, not left written.
    assert wrote.read_text(encoding="utf-8") == "ORIGINAL-CONTENT\n"


def test_partial_apply_removes_a_newly_created_file_on_restore(tmp_path):
    root = str(tmp_path)
    created = tmp_path / "new.py"
    created.write_text("brand-new\n", encoding="utf-8")
    snapshot = {"new.py": None}  # None snapshot = file did not exist before
    applied = PatchApplyResult(
        project_root=root,
        changed_files=["new.py"],
        skipped_files=["other.py"],
        ok=True,
    )
    patch_requests = [{"path": "new.py", "new_content": "brand-new\n"}]
    _bridge()._partial_or_noop_block(
        root, snapshot, applied, patch_requests, "t", "auto")
    assert not created.exists()


# ---------------------------------------------------------------------------
# _partial_or_noop_block — NO-OP apply: every written file equals what was
# already there (empty diff), which is not a fix and must be blocked + restored.
# ---------------------------------------------------------------------------
def test_noop_apply_blocks_with_noop_reason(tmp_path):
    root = str(tmp_path)
    f = tmp_path / "same.py"
    f.write_text("identical\n", encoding="utf-8")
    snapshot = {"same.py": "identical\n"}
    applied = PatchApplyResult(
        project_root=root, changed_files=["same.py"], skipped_files=[], ok=True)
    patch_requests = [{"path": "same.py", "new_content": "identical\n"}]
    block = _bridge()._partial_or_noop_block(
        root, snapshot, applied, patch_requests, "redundant_else", "auto")

    assert block is not None
    assert block["applied"] is False
    assert block["reason"] == "no change (patch is a no-op)"
    assert block["transform_type"] == "redundant_else"
    # A no-op carries no skipped_files key (only the partial branch sets it).
    assert "skipped_files" not in block


def test_noop_apply_restores_each_written_file(tmp_path):
    root = str(tmp_path)
    f = tmp_path / "same.py"
    # On disk the writer left the same content; snapshot is byte-identical.
    f.write_text("identical\n", encoding="utf-8")
    snapshot = {"same.py": "identical\n"}
    applied = PatchApplyResult(
        project_root=root, changed_files=["same.py"], skipped_files=[], ok=True)
    patch_requests = [{"path": "same.py", "new_content": "identical\n"}]
    _bridge()._partial_or_noop_block(root, snapshot, applied, patch_requests, "t", "x")
    assert f.read_text(encoding="utf-8") == "identical\n"


def test_real_change_is_not_blocked(tmp_path):
    # A genuine multi-file-free change that actually differs from the snapshot
    # must pass through (return None) so the apply proceeds.
    root = str(tmp_path)
    f = tmp_path / "real.py"
    f.write_text("AFTER\n", encoding="utf-8")
    snapshot = {"real.py": "BEFORE\n"}
    applied = PatchApplyResult(
        project_root=root, changed_files=["real.py"], skipped_files=[], ok=True)
    patch_requests = [{"path": "real.py", "new_content": "AFTER\n"}]
    block = _bridge()._partial_or_noop_block(root, snapshot, applied, patch_requests, "t", "x")
    assert block is None
    # And the real change is left in place (not restored).
    assert f.read_text(encoding="utf-8") == "AFTER\n"


def test_partial_branch_takes_priority_over_noop_check(tmp_path):
    # A skipped file forces the PARTIAL reason even when the written file would
    # otherwise look like a no-op — the partial branch is checked first.
    root = str(tmp_path)
    f = tmp_path / "same.py"
    f.write_text("identical\n", encoding="utf-8")
    snapshot = {"same.py": "identical\n"}
    applied = PatchApplyResult(
        project_root=root,
        changed_files=["same.py"],
        skipped_files=["skipped.py"],
        ok=True,
    )
    patch_requests = [
        {"path": "same.py", "new_content": "identical\n"},
        {"path": "skipped.py", "new_content": "x\n"},
    ]
    block = _bridge()._partial_or_noop_block(root, snapshot, applied, patch_requests, "t", "x")
    assert block is not None
    assert block["reason"] == "partial apply (expected_old_content mismatch)"


def test_noop_guard_requires_applied_ok(tmp_path):
    # The no-op branch only fires when ``applied.ok`` — a failed write
    # (ok=False) with no skipped files is NOT reported as a no-op fix.
    root = str(tmp_path)
    f = tmp_path / "same.py"
    f.write_text("identical\n", encoding="utf-8")
    snapshot = {"same.py": "identical\n"}
    applied = PatchApplyResult(
        project_root=root, changed_files=["same.py"], skipped_files=[], ok=False)
    patch_requests = [{"path": "same.py", "new_content": "identical\n"}]
    block = _bridge()._partial_or_noop_block(root, snapshot, applied, patch_requests, "t", "x")
    assert block is None


def test_noop_detected_across_multiple_changed_files(tmp_path):
    # If EVERY changed file is byte-identical to its snapshot it is a no-op,
    # even across several files.
    root = str(tmp_path)
    (tmp_path / "a.py").write_text("same-a\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("same-b\n", encoding="utf-8")
    snapshot = {"a.py": "same-a\n", "b.py": "same-b\n"}
    applied = PatchApplyResult(
        project_root=root, changed_files=["a.py", "b.py"], skipped_files=[], ok=True)
    patch_requests = [
        {"path": "a.py", "new_content": "same-a\n"},
        {"path": "b.py", "new_content": "same-b\n"},
    ]
    block = _bridge()._partial_or_noop_block(root, snapshot, applied, patch_requests, "t", "x")
    assert block is not None
    assert block["reason"] == "no change (patch is a no-op)"


def test_one_real_change_among_noops_is_not_blocked(tmp_path):
    # ``no_change`` is "NONE of the changed files differ"; a single real diff
    # among identical files means it is NOT a no-op (the apply proceeds).
    root = str(tmp_path)
    (tmp_path / "a.py").write_text("same-a\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("AFTER-b\n", encoding="utf-8")
    snapshot = {"a.py": "same-a\n", "b.py": "BEFORE-b\n"}
    applied = PatchApplyResult(
        project_root=root, changed_files=["a.py", "b.py"], skipped_files=[], ok=True)
    patch_requests = [
        {"path": "a.py", "new_content": "same-a\n"},
        {"path": "b.py", "new_content": "AFTER-b\n"},
    ]
    block = _bridge()._partial_or_noop_block(root, snapshot, applied, patch_requests, "t", "x")
    assert block is None
