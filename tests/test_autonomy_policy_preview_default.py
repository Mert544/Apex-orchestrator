"""PREVIEW-by-default gate on the AutonomyPolicy (the `apex auto` footgun fix).

``require_explicit_apply`` makes the policy RECOMMEND (never touch the tree)
unless ``--apply`` was passed — so a bare ``apex auto`` can't silently edit a
clean tree (it once edited Apex's own repo). The flag defaults OFF, so every
existing consumer (the dashboard "what would auto do" panel, the legacy
unattended path) is byte-identical.

Each new assertion was verified to FAIL pre-change (the flag did not exist).
"""

from __future__ import annotations

from app.policies.autonomy_policy import AutonomyPolicy


def test_require_explicit_apply_previews_without_apply():
    # Clean tree + safe work, but no explicit --apply -> PREVIEW (act False).
    d = AutonomyPolicy().decide(
        executable_steps=4, working_tree_clean=True, require_explicit_apply=True)
    assert d.act is False and d.mode == "report"
    assert "--apply" in d.reason


def test_require_explicit_apply_still_acts_with_apply():
    # The explicit opt-in always wins over the preview gate.
    d = AutonomyPolicy().decide(
        executable_steps=4, working_tree_clean=True, explicit_apply=True,
        require_explicit_apply=True)
    assert d.act is True and d.mode == "supervised"


def test_require_explicit_apply_nothing_to_do_stays_honest():
    # A clean, debt-free project reads "no safe fixes", not a misleading "preview".
    d = AutonomyPolicy().decide(
        executable_steps=0, working_tree_clean=True, require_explicit_apply=True)
    assert d.act is False
    assert "no safe" in d.reason


def test_off_by_default_is_byte_identical_clean_tree():
    # Without the flag, the historical clean-tree auto-apply is unchanged — the
    # unattended daemon / dashboard decision must not shift.
    d = AutonomyPolicy().decide(executable_steps=4, working_tree_clean=True)
    assert d.act is True and d.mode == "supervised"
    assert "applying" in d.reason.lower()
