from app.policies.mode_policy import (
    ApexMode,
    ModePolicy,
    apply_cli_overrides,
    mode_from_string,
)


def test_mode_from_string():
    assert mode_from_string(None) == ApexMode.SUPERVISED
    assert mode_from_string("report") == ApexMode.REPORT
    assert mode_from_string("autonomous") == ApexMode.AUTONOMOUS
    assert mode_from_string("bogus") == ApexMode.SUPERVISED  # safe default


def test_permissions_per_mode():
    assert ModePolicy(mode=ApexMode.REPORT).permissions.can_patch is False
    sup = ModePolicy(mode=ApexMode.SUPERVISED).permissions
    assert sup.can_patch is True and sup.can_commit is False
    auto = ModePolicy(mode=ApexMode.AUTONOMOUS).permissions
    assert auto.can_patch is True and auto.can_commit is True


def test_can_write_can_commit():
    assert ModePolicy(mode=ApexMode.REPORT).can_write() is False
    assert ModePolicy(mode=ApexMode.SUPERVISED).can_write() is True
    assert ModePolicy(mode=ApexMode.AUTONOMOUS).can_commit() is True


def test_summary_and_to_dict():
    policy = ModePolicy(mode=ApexMode.SUPERVISED)
    summary = policy.summary()
    assert summary["mode"] == "supervised"
    assert "permissions" in summary
    assert policy.to_dict() == summary


def test_apply_cli_overrides():
    policy = ModePolicy(mode=ApexMode.SUPERVISED)
    apply_cli_overrides(policy, auto_patch=True, auto_commit=True,
                        max_fractal_budget=42, safety_policy="strict")
    assert policy.auto_patch is True
    assert policy.auto_commit is True
    assert policy.max_fractal_budget == 42
    assert policy.safety_policy == "strict"


def test_apply_cli_overrides_none_keeps_defaults():
    policy = ModePolicy(mode=ApexMode.SUPERVISED)
    before = (policy.auto_patch, policy.safety_policy)
    apply_cli_overrides(policy, None, None, None, None)
    assert (policy.auto_patch, policy.safety_policy) == before


def test_enforce_clean_working_tree_dirty(tmp_path, monkeypatch):
    # Simulate a dirty tree via a fake subprocess result.
    import subprocess as sp

    class _Res:
        stdout = " M somefile.py\n"

    monkeypatch.setattr(sp, "run", lambda *a, **k: _Res())
    result = ModePolicy(mode=ApexMode.AUTONOMOUS).enforce_clean_working_tree()
    assert result.passed is False
    assert result.blocked is True


def test_enforce_clean_working_tree_clean(monkeypatch):
    import subprocess as sp

    class _Res:
        stdout = ""

    monkeypatch.setattr(sp, "run", lambda *a, **k: _Res())
    result = ModePolicy(mode=ApexMode.AUTONOMOUS).enforce_clean_working_tree()
    assert result.passed is True
