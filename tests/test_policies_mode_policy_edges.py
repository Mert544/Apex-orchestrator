"""Branch coverage for the remaining edges of app.policies.mode_policy.

The sibling tests/test_policies_mode_policy.py covers the happy paths; these pin
the leftover branches:

  - __post_init__ early-returns (skips ApexMode coercion) when `mode` is already
    an ApexMode enum (a str subclass check that is False for the enum member);
  - the `permissions` property returns `custom_permissions` verbatim when set;
  - enforce_clean_working_tree's except arm: a subprocess failure is reported as
    blocked, not raised.

Subprocess is monkeypatched so nothing spawns git; no wall-clock asserts.
"""

from __future__ import annotations

import subprocess as sp

from app.policies.mode_policy import (
    ApexMode,
    ModePermissions,
    ModePolicy,
)


def test_post_init_coerces_enum_member_through_apexmode():
    # ApexMode is a str Enum, so a member passes the `isinstance(str)` guard and
    # is re-wrapped by ApexMode(...); the round-trip yields the same member.
    policy = ModePolicy(mode=ApexMode.AUTONOMOUS)
    assert policy.mode is ApexMode.AUTONOMOUS


def test_post_init_non_string_mode_returns_early():
    # Passing a non-str, non-ApexMode value exercises the `not isinstance str`
    # early return: the attribute is left untouched (no ApexMode coercion).
    sentinel = object()
    policy = ModePolicy(mode=sentinel)  # type: ignore[arg-type]
    assert policy.mode is sentinel


def test_custom_permissions_take_priority():
    custom = ModePermissions(can_patch=True, can_commit=True, max_changed_files=99)
    policy = ModePolicy(mode=ApexMode.REPORT, custom_permissions=custom)
    perms = policy.permissions
    assert perms is custom
    assert perms.max_changed_files == 99
    # can_write/can_commit read through the custom permissions, not the REPORT map.
    assert policy.can_write() is True
    assert policy.can_commit() is True


def test_enforce_clean_working_tree_subprocess_error_blocks(monkeypatch):
    def boom(*a, **k):
        raise sp.TimeoutExpired(cmd="git", timeout=10)

    monkeypatch.setattr(sp, "run", boom)
    result = ModePolicy(mode=ApexMode.AUTONOMOUS).enforce_clean_working_tree()
    assert result.passed is False
    assert result.blocked is True
    assert "Could not verify working tree" in result.message
